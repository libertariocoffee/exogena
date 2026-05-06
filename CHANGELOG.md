# Changelog

Todas las modificaciones notables a este módulo se registran en este archivo.

El formato sigue el espíritu de [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el módulo usa versionado semántico relativo a la versión Odoo: `17.0.<MAJOR>.<MINOR>`.

---

## [17.0.1.1] — 2026-05-05

### Resumen

Optimización de rendimiento de `generate_and_download_report` para que el reporte
escale con datasets anuales. Antes: el botón "Generar y descargar reporte" colgaba
el worker HTTP cuando se seleccionaba un período largo (un año entero) hasta que
Odoo lo mataba por `limit_time_real` / `limit_time_cpu`. Ahora: corre en segundos
sobre 7.5 millones de líneas contables.

**Cambio cualitativo medido en producción** (formato 1001, año 2025, dataset real):

| | `account.move.line` posted | Tiempo | Estado |
|---|---:|---:|---|
| Código original | 7,496,657 | >60 s | Timeout del worker |
| Código optimizado (1ª corrida, BD fría) | 7,496,657 | 19.6 s | OK |
| Código optimizado (2ª corrida, BD caliente) | 7,496,657 | **2.764 s** | OK |

Filas del Excel generado: 659. SHA256 del output (oráculo de regresión):
`d8e3b3c9e3f2d9f55e4640b68ae3b078cf3b9a4ad5973089a5c6b019dcd854ed`.

### Cambiado

#### Paso 1 — `_select_fields_from_account_move_line` vectorizado
- Reemplazado `df.apply(get_column_value, axis=1)` por operaciones vectorizadas
  con `Series.map` y máscaras booleanas. La función Python que se invocaba una
  vez por fila ya no existe; las seis ramas de cálculo (`debit`, `credit`,
  `balance`, `tax_base_amount`, `tax_amount`, `closing_balance` × dos modos
  `asset_liability` y `account_prefix`) se aplican como asignaciones por máscara.
- Pre-construye `op_by_id`, `display_name_by_id` y `sign_by_id` aplanando las
  llaves de `account_operations` (que vienen como tuplas `(id, display_name)`)
  a un solo `int`. Esto permite que `Series.map` opere en C-level.
- Constantes `_DEBIT_NATURE_ACCOUNT_TYPES` y `_CREDIT_NATURE_ACCOUNT_TYPES`
  movidas a atributos de clase como `frozenset`.
- Ganancia esperada: 50–200× sobre esta operación específica.

#### Paso 2 — `_read_group` generalizado a todos los métodos de acumulación
- Nuevo helper `_read_group_account_move_lines(field_account, *, extra_domain,
  include_no_partner)` que agrega `account.move.line` a nivel SQL por
  `(account_id, partner_id)` con `balance:sum`, `debit:sum`, `credit:sum`,
  `tax_base_amount:sum`. Antes solo `closing_balance` agregaba en SQL; el resto
  hacía `search_read` materializando cada línea individual a Python.
- `_get_closing_balance_by_read_group` ahora es un wrapper delgado que delega
  al helper anterior, preservando la firma pública y la semántica de excluir
  filas sin partner.
- `_get_information_by_account_move_line` despacha por método:
  - `closing_balance` → wrapper anterior.
  - `tax_amount` → `_read_group` con dominio adicional `('tax_line_id', '!=', False)`.
  - resto → `_read_group` con dominio de fechas estándar.
- Ganancia esperada: 10–50× sobre el fetch (depende del fan-out partner×cuenta).

#### Paso 3 — `_normalize_partner_identification` vectorizado
- Reemplazado `df.apply(process_identification, axis=1)` por:
  - Split vectorizado vía `Series.str.partition('-')`.
  - Cómputo de DV (`_check_dv`) **una sola vez por NIT único** vía `pd.unique` +
    `dict.map`. Antes se llamaba `_check_dv` una vez por fila aunque hubiera
    NITs repetidos.
- `tools/utils.py:_check_dv()` no se modificó (algoritmo DIAN módulo-11 oficial).

#### Paso 5 — Caching de partners entre `setting_lines`
- `generate_and_download_report` reestructurado en tres fases:
  1. Recolectar AML agregadas y unión de `partner_ids` por todos los
     `setting_line_ids`.
  2. Una sola llamada a `_get_information_partner` con la unión de IDs +
     un solo `_normalize_partner_dataframe`.
  3. Loop por `setting_line` que solo hace split (con/sin partner) + merge
     contra el frame cacheado + aplicar método de acumulación + concat.
- Antes, para un formato 1001 con 5 campos monetarios, se ejecutaban 5
  `search_read` redundantes a `res.partner` y 5 normalizaciones idénticas.
  Ahora se hace una vez.

### Agregado

- `tools/benchmark_report.py`: harness para producir baseline reproducible.
  Genera el `.xlsx` desde el setting indicado, lo guarda en `/tmp`, calcula
  un SHA256 normalizado del dataframe (filas ordenadas + columnas tipadas a
  enteros) y permite hacer diff celda a celda contra un oráculo previo.
  Funciones: `run_baseline(setting, label)`, `diff_against_oracle(a, b)`.
  Uso documentado en su docstring.

### Cambio de semántica documentado (a validar por el revisor humano)

El método `tax_amount` cambia de `Σ |balance_i|` (sumar valores absolutos por
fila) a `|Σ balance_i|` (valor absoluto del agregado SQL). Son equivalentes
cuando el signo de `balance` dentro de un bucket `(account, partner)` es
constante — el caso típico de líneas de impuesto en formatos 1005/1006.

Si el cliente factura **y** emite notas crédito sobre el mismo partner contra
la misma cuenta de impuesto en el mismo período, el valor reportado puede
diferir del comportamiento previo. El nuevo valor es el **neto** (lo que la
DIAN típicamente espera); el anterior era el **bruto** (suma de flujos
independiente de signo).

### No cambiado

- Convenciones DIAN preservadas: `abs()` final en `_clean_dataframe_for_export`,
  `max_length` por campo, `number_format='0'` para enteros sin decimales ni
  separadores en celdas numéricas.
- XML IDs hardcoded de los format_fields (`_cpt`, `_tdoc`, `_nid`, `_raz`,
  `_dv`, `_dpto`, `_pais`) intactos.
- Constraint `UNIQUE(format_field_id, concept_id, name)` en
  `l10n_co.exogenous_format_field_account` intacto.
- Filtros `company_id` en todos los queries preservados.
- Lógica de cuantías menores (`process_smaller_amount_dataframe`) y de la
  fila "Movimientos sin terceros" inalteradas.
- Algoritmo de DV (`_check_dv`) sin tocar.
- API pública: `_get_closing_balance_by_read_group(field_account)` y
  `_get_information_by_account_move_line(field_account)` mantienen firma y
  shape de retorno.

### Verificaciones de corrección realizadas

1. Suite sintética `verify_select_fields.py` (8 casos cubriendo cada rama del
   método de acumulación, con oráculo `apply(axis=1)` de la versión anterior):
   `ALL OK`.
2. Suite sintética `verify_normalize_id.py` (3 casos: NITs reales mixtos,
   sin filas NIT, todas falsy): `ALL OK`.
3. Validación de sintaxis Python (`ast.parse`) tras cada paso: OK.
4. Producción con dataset real del cliente, formato 1001 año 2025
   (7,496,657 líneas posted): `diff_against_oracle` reporta
   `OK: oracle == candidate (659 rows)` entre dos corridas independientes.
   Output determinístico — mismo SHA256.

### Limitación conocida (pre-existente, no introducida en esta versión)

`_clean_dataframe_for_export` línea ~798 emite un `FutureWarning` de pandas
sobre downcasting silencioso en `.fillna(0)`. Ya existía antes. Se vuelve
error en pandas 3.0. Mitigación cuando aplique: usar
`df[col].fillna(0).infer_objects(copy=False)` o
`pd.set_option('future.no_silent_downcasting', True)`.

---

## [17.0.1.3] — 2026-05-05

### Corregido

- **`KeyError: 'account_id'`** en `generate_and_download_report` durante la
  agregación de "Movimientos sin terceros" cuando ningún `setting_line`
  produce filas sin partner. Bug latente del código original, no
  introducido por las optimizaciones — solo se hace evidente cuando los
  datos del cliente no contienen líneas contables sin tercero asignado.
  Ahora el bloque detecta el caso (`original_dataframe_without_partner`
  vacío o sin columna `account_id`) y se salta tanto el `groupby` como
  el `for row_data in dataframe_to_rows(...)` aguas abajo. La rama
  no-`apply_concepts` también deja de generar una fila sintética de
  ceros que el filtro all-zero borraba después; ahora simplemente no
  agrega nada en ese caso.

---

## [17.0.1.2] — 2026-05-05

### Resumen

Cambios defensivos para escalar de 14 → 38 tiendas (proyección ~20 M
líneas contables/año). El núcleo del generador ya escala bien por la
agregación SQL del 17.0.1.1; estos cambios cubren los flecos.

### Cambiado

- **`_clean_dataframe_for_export`**:
  - Eliminado el `df[col].fillna(0)` sobre object dtype que emitía
    `FutureWarning` y se vuelve `TypeError` en pandas 3.0. Ahora se
    usa `pd.to_numeric(..., errors='coerce').fillna(0.0)` que tiene
    semántica equivalente sin la advertencia.
  - Truncado de campos numéricos por `max_length`: `df[col].apply(
    lambda x: min(x, max_value))` reemplazado por
    `df[col].clip(upper=max_value)` (vectorizado, sin Python apply).
  - Truncado de campos texto por `max_length`: `df[col].astype(str).
    apply(lambda x: x[:max_len] if x else '')` reemplazado por
    `df[col].fillna('').astype(str).str.slice(0, max_len)`.

### Agregado

- `docs/SCALABILITY.md`: notas operacionales con proyección a 38
  tiendas, recomendaciones de índices PostgreSQL para el DBA, plan
  de monitoreo, y umbrales para reconsiderar optimizaciones futuras.

### Por qué hago esto ahora

- Los tres `apply`/`fillna` de `_clean_dataframe_for_export` corren
  sobre el dataframe **final** (cientos a miles de filas), no sobre
  los millones de líneas contables. La ganancia de tiempo es
  marginal hoy (<100 ms). El valor real es:
  1. Eliminar la bomba de tiempo de pandas 3.0.
  2. Mantener la disciplina vectorizada en todo el pipeline para
     que cualquier ingeniero futuro que toque este archivo siga el
     mismo patrón.
- Los índices PostgreSQL no se aplican vía código del módulo porque
  son decisión del DBA del cliente y `CREATE INDEX CONCURRENTLY` no
  encaja en el flujo de `data/*.xml`. Quedan documentados.

### Verificaciones

- Validación de sintaxis Python (`ast.parse`): OK.
- Lógica equivalente: `clip(upper=N)` ≡ `min(x, N)` para enteros
  positivos (todos los valores acá ya son ≥ 0 tras el `abs()`).
  `str.slice(0, N)` ≡ `s[:N]` para strings; `s[:N]` sobre `''`
  retorna `''`, igual que el lambda anterior. `pd.to_numeric(...).
  fillna(0.0)` produce el mismo resultado que `fillna(0)` seguido
  de `pd.to_numeric(...).fillna(0)` para columnas numéricas mixtas.
- Diff cero esperado contra el oráculo SHA256
  `d8e3b3c9e3f2d9f55e4640b68ae3b078cf3b9a4ad5973089a5c6b019dcd854ed`
  del 17.0.1.1.

---

## [17.0.1.0] — versión inicial

Estado del módulo previo a esta optimización. Funcionaba para reportes
mensuales pero fallaba con períodos largos por timeout del worker HTTP.
