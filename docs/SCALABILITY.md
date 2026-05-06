# Escalabilidad y operación

Notas operacionales para mantener el reporte exógeno corriendo en tiempo
razonable a medida que el dataset crece (ej.: ampliación de 14 → 38 tiendas).

## Datos de referencia (medidos en producción)

| Configuración | `account.move.line` posted/año | Tiempo total | Worker |
|---|---:|---:|---|
| 14 tiendas, 1001 año 2025 (cold) | 7,496,657 | 19.6 s | OK |
| 14 tiendas, 1001 año 2025 (warm) | 7,496,657 | 2.764 s | OK |

Output: 659 filas, 11 columnas.
SHA256 oráculo: `d8e3b3c9e3f2d9f55e4640b68ae3b078cf3b9a4ad5973089a5c6b019dcd854ed`.

## Proyección a 38 tiendas

Asumiendo crecimiento aproximadamente lineal en líneas contables:

| Métrica | Hoy | Proyección 38 tiendas | Comentario |
|---|---:|---:|---|
| Líneas contables/año | 7.5 M | ~20 M | × 2.71 |
| Tiempo SQL `_read_group` | ~1.5 s warm | ~4–6 s warm | El planner debería seguir usando index scan |
| Filas tras agregación SQL | ~hundreds | ~thousands | Cota: partners × cuentas configuradas |
| Tiempo total esperado | 2.7 s warm | **6–10 s warm / 30–50 s cold** | Holgado vs `limit_time_real` típico (60–120 s) |

El cuello de botella se mueve a PostgreSQL: si el SQL escala bien, el
reporte escala bien. Las optimizaciones del 2026-05-05 estructuran el
flujo para que toda la carga pesada quede del lado de la BD.

## Recomendaciones para el DBA

### 1. Verificar/crear índice compuesto en `account_move_line`

Odoo crea por defecto índices simples sobre `account_id`, `move_id`,
`partner_id`. Para los queries del exógeno (filtros combinados de
`account_id` + `parent_state` + `date` + `company_id`), un índice
compuesto puede mejorar el plan.

```sql
-- Verificar plan actual sobre un query típico del módulo:
EXPLAIN ANALYZE
SELECT account_id, partner_id,
       SUM(balance), SUM(debit), SUM(credit), SUM(tax_base_amount)
FROM account_move_line
WHERE parent_state = 'posted'
  AND company_id = 1
  AND account_id IN (4523, 4524, 4525)
  AND date >= '2025-01-01' AND date <= '2025-12-31'
GROUP BY account_id, partner_id;

-- Si el plan muestra "Seq Scan" o el tiempo > 5s sobre 20M+ rows:
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aml_exogenous_lookup
ON account_move_line (account_id, parent_state, date)
WHERE parent_state = 'posted';
```

`CREATE INDEX CONCURRENTLY` no bloquea writes pero tarda más. Sobre
20 M filas puede tomar 5–15 minutos. Hacerlo en horario de baja carga.

El predicado parcial `WHERE parent_state = 'posted'` reduce el tamaño
del índice ~50% porque excluye drafts/cancels que el reporte nunca lee.

### 2. Asegurar `VACUUM ANALYZE` reciente

```sql
-- Verificar última estadística:
SELECT relname, last_analyze, last_autoanalyze, n_live_tup, n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'account_move_line';

-- Forzar manual si está desactualizado:
VACUUM ANALYZE account_move_line;
```

Auto-vacuum debería manejarlo, pero después de cargas masivas
(migraciones, importaciones) conviene forzarlo.

### 3. Monitor de tamaño de tabla

```sql
SELECT pg_size_pretty(pg_total_relation_size('account_move_line'));
```

Cuando supere ~50 GB el patrón de scaling cambia (más presión sobre
buffer pool). En ese punto vale repensar particionamiento por año.

## Cuándo volver a considerar optimizaciones

- **Si el reporte cold supera 60 s** → revisar plan SQL con `EXPLAIN
  ANALYZE`. Posible falta de índice.
- **Si hay >50K partners únicos en el reporte** → considerar batching
  de `_get_information_partner` en chunks de 5K.
- **Si la tabla `account_move_line` supera 100 GB** → considerar
  particionamiento por rango de `date`.
- **Si Odoo migra a pandas 3.0** → revisar advertencias de
  `FutureWarning` que se hayan acumulado. Ya cubrimos las conocidas
  al 2026-05-05.

## Cómo medir antes/después de cualquier cambio

Usar `tools/benchmark_report.py`:

```python
from odoo.addons.l10n_co_exogenous_information_reporting.tools.benchmark_report import (
    run_baseline, diff_against_oracle,
)
setting = env['l10n_co.exogenous_format_setting'].browse(SETTING_ID)
result = run_baseline(setting, label='monthly_check')
# result['sha256'] debe coincidir con el oráculo del CHANGELOG.
# result['timings']['total'] es la métrica a trackear.
```

Recomendación: correr una vez al mes con el mismo setting y graficar
`timings['total']` para detectar degradación temprana.
