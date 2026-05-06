# Arquitectura del Formato 1001 - Información Exógena DIAN

## Resumen Ejecutivo

El módulo `l10n_co_exogenous_information_reporting` implementa un **enfoque configurable y flexible** para la generación de reportes de información exógena de la DIAN. La arquitectura permite configurar formatos sin modificar código, únicamente mediante datos XML.

## ✅ Validación del Enfoque

**Tu arquitectura es CORRECTA y está bien diseñada.** El módulo separa claramente:
- **Configuración** (datos XML)
- **Lógica de negocio** (código Python)
- **Modelos de datos** (modelos Odoo)

## Modelos Principales

### 1. `l10n_co.exogenous_format`
Define el formato general de reporte DIAN.

**Campos Clave:**
- `code`: Código del formato (ej: "1001")
- `apply_concepts`: Si usa conceptos DIAN para agrupar
- `applying_smaller_amounts`: Si agrupa cuantías menores
- `smaller_ammounts`: Umbral de cuantías menores

**Ejemplo Formato 1001:**
```xml
<record id="l10n_co_exogenous_format_1001" model="l10n_co.exogenous_format">
    <field name="name">Pagos o abonos en cuenta y retenciones practicadas</field>
    <field name="code">1001</field>
    <field name="apply_concepts" eval="True"/>
    <field name="applying_smaller_amounts" eval="True"/>
    <field name="smaller_ammounts" eval="100000"/>
</record>
```

---

### 2. `l10n_co.exogenous_format_field`
Define cada campo (columna) del reporte.

**Campos Clave:**
- `name`: Nombre del campo (ej: "Pago o abono en cuenta deducible")
- `attribute`: Código del atributo (ej: "pago", "retp")
- `source`: Origen de datos ('contact', 'journal_items', 'resolution')
- `format_ids`: Formatos donde se usa este campo
- `is_unique_key`: Si es llave única para agrupación

**Campos Formato 1001:**
1. **pago**: Pago o abono deducible
2. **pnded**: Pago o abono NO deducible
3. **ided**: IVA mayor valor costo deducible
4. **inded**: IVA mayor valor costo NO deducible
5. **retp**: Retención practicada Renta
6. **reta**: Retención asumida Renta
7. **comun**: Retención IVA responsables
8. **ndom**: Retención IVA no domiciliados

---

### 3. `l10n_co.exogenous_format_field_account` ⭐ **MODELO CLAVE**
Mapea cuentas contables a campos específicos por concepto.

**Campos Clave:**
- `format_field_id`: Campo del formato (ej: "pago")
- `name`: Método de acumulación ('debit', 'credit', 'balance', 'tax_base_amount', 'tax_amount', 'closing_balance')
- `account_ids`: Cuentas contables a incluir
- `concept_id`: Concepto DIAN (opcional, solo si formato aplica conceptos)

**Constraint SQL:**
```sql
UNIQUE(format_field_id, concept_id, name)
```
Previene duplicados en la configuración.

---

### 4. `l10n_co.exogenous_concept`
Define conceptos DIAN para agrupar transacciones.

**Campos Clave:**
- `code`: Código del concepto (ej: "5002", "5003")
- `name`: Descripción del concepto
- `format_id`: Formato al que pertenece

**Conceptos Formato 1001 (Ejemplos):**
- **5002**: Honorarios
- **5003**: Comisiones
- **5004**: Servicios
- ...

---

## Configuración Formato 1001

### Ejemplo Completo: Campo "pago" (Pago Deducible)

```xml
<!-- 1. Definir el campo -->
<record id="format_field_pago" model="l10n_co.exogenous_format_field">
    <field name="name">Pago o abono en cuenta deducible</field>
    <field name="attribute">pago</field>
    <field name="source">journal_items</field>
    <field name="format_ids" eval="[(6, 0, [ref('l10n_co_exogenous_format_1001')])]"/>
    <field name="format_applies_concepts" eval="True"/>
</record>

<!-- 2. Configurar cuentas por concepto -->
<!-- Concepto 5002 - Honorarios -->
<record id="field_account_pago_5002" model="l10n_co.exogenous_format_field_account">
    <field name="format_field_id" ref="format_field_pago"/>
    <field name="name">debit</field>
    <field name="concept_id" ref="concepto_5002"/>
    <field name="account_ids" eval="[(6, 0, [
        ref('account.account_511010'),
        ref('account.account_511025'),
    ])]"/>
</record>

<!-- Concepto 5003 - Comisiones -->
<record id="field_account_pago_5003" model="l10n_co.exogenous_format_field_account">
    <field name="format_field_id" ref="format_field_pago"/>
    <field name="name">debit</field>
    <field name="concept_id" ref="concepto_5003"/>
    <field name="account_ids" eval="[(6, 0, [
        ref('account.account_529505'),
    ])]"/>
</record>

<!-- Concepto 5004 - Servicios -->
<record id="field_account_pago_5004" model="l10n_co.exogenous_format_field_account">
    <field name="format_field_id" ref="format_field_pago"/>
    <field name="name">debit</field>
    <field name="concept_id" ref="concepto_5004"/>
    <field name="account_ids" eval="[(6, 0, [
        ref('account.account_513xxx'),
        ref('account.account_513yyy'),
    ])]"/>
</record>
```

### Ejemplo Completo: Campo "retp" (Retención Renta)

```xml
<record id="format_field_retp" model="l10n_co.exogenous_format_field">
    <field name="name">Retención en la fuente practicada Renta</field>
    <field name="attribute">retp</field>
    <field name="source">journal_items</field>
</record>

<!-- Las retenciones son CRÉDITOS en la cuenta por pagar -->
<record id="field_account_retp_5002" model="l10n_co.exogenous_format_field_account">
    <field name="format_field_id" ref="format_field_retp"/>
    <field name="name">credit</field>  <!-- Nota: credit, no debit -->
    <field name="concept_id" ref="concepto_5002"/>
    <field name="account_ids" eval="[(6, 0, [
        ref('account.account_236505'),  <!-- Retenciones por pagar -->
    ])]"/>
</record>
```

---

## Flujo de Generación del Reporte

### 1. Usuario Configura `l10n_co.exogenous_format_setting`

```python
# Usuario crea una configuración de reporte
setting = env['l10n_co.exogenous_format_setting'].create({
    'format_id': ref('l10n_co_exogenous_format_1001'),
    'date_start': '2025-01-01',
    'date_end': '2025-12-31',
    'format_setting_line_ids': [(0, 0, {
        'format_field_id': ref('format_field_pago'),
    }), (0, 0, {
        'format_field_id': ref('format_field_retp'),
    }), ...]
})
```

### 2. Ejecuta `generate_and_download_report()`

#### **Paso 2.1: Loop por Campo (setting_line)**

Para cada campo configurado (pago, pnded, retp...):

```python
for setting_line in self.format_setting_line_ids:
    # Obtiene todas las configuraciones de cuentas del campo
    field_accounts = setting_line.format_field_id.field_account_ids
    # field_accounts = [
    #   (campo=pago, concepto=5002, método=debit, cuentas=[51xx]),
    #   (campo=pago, concepto=5003, método=debit, cuentas=[52xx]),
    #   ...
    # ]
```

#### **Paso 2.2: Consulta `account.move.line`**

Por cada configuración de cuenta:

```python
for field_account in field_accounts:
    # Consulta movimientos contables de las cuentas configuradas
    domain = [
        ('account_id', 'in', field_account.account_ids.ids),
        ('date', '>=', self.date_start),
        ('date', '<=', self.date_end),
        ('parent_state', '=', 'posted'),
    ]
    
    account_move_lines = env['account.move.line'].search_read(
        domain, 
        fields=['credit', 'debit', 'balance', 'partner_id', 'account_id']
    )
```

#### **Paso 2.3: Aplica Método de Acumulación**

```python
# Método _select_fields_from_account_move_line
# Crea una nueva columna con el nombre del campo

if field_account.name == 'debit':
    df['Pago o abono en cuenta deducible'] = df['debit']
elif field_account.name == 'credit':
    df['Retención en la fuente practicada Renta'] = df['credit']
elif field_account.name == 'balance':
    df['IVA mayor valor del costo'] = df['balance']
```

#### **Paso 2.4: Obtiene Información de Partners**

```python
# Extrae partner_ids únicos
partner_ids = set([aml['partner_id'][0] for aml in account_move_lines])

# Consulta información del partner
partners = env['res.partner'].search_read(
    [('id', 'in', list(partner_ids))],
    fields=['vat', 'name', 'l10n_latam_identification_type_id', ...]
)
```

#### **Paso 2.5: Merge y Normalización**

```python
# Fusiona datos contables con datos de partners
df_result = pd.merge(df_account_move_lines, df_partners, on='partner_id')

# Normaliza:
# - Mapea tipos de documento Odoo → Códigos DIAN
# - Calcula dígito de verificación
# - Normaliza direcciones (códigos departamento/municipio)
```

### 3. Agrupación Final

```python
# Agrupa por llaves únicas: (tdoc, nid, concepto)
unique_keys = ['l10n_latam_identification_type_id', 'vat', 'account_id']

operations = {
    'vat': 'first',  # Campos de contacto: primer valor
    'name': 'first',
    'Pago o abono en cuenta deducible': 'sum',  # Campos monetarios: suma
    'Retención en la fuente practicada Renta': 'sum',
}

result = df.groupby(unique_keys).agg(operations)
```

**Resultado:**

| tdoc | nid       | cpt  | raz              | pago    | retp  |
|------|-----------|------|------------------|---------|-------|
| 31   | 900123456 | 5002 | PROVEEDOR S.A.S. | 1000000 | 11000 |
| 31   | 900456789 | 5003 | CONSULTOR LTDA   | 500000  | 5500  |

---

## Ventajas de la Arquitectura

### ✅ **1. Configurable**
No necesitas modificar código para:
- Agregar nuevos campos
- Cambiar cuentas contables
- Modificar conceptos DIAN
- Ajustar métodos de acumulación

### ✅ **2. Reutilizable**
La misma lógica sirve para:
- Formato 1001 (Pagos y retenciones)
- Formato 1003 (Retenciones recibidas)
- Formato 1005, 1006, etc.

### ✅ **3. Auditable**
Puedes rastrear:
- Qué cuentas se usan en cada campo
- Qué método de cálculo se aplica
- Historial de cambios en configuración

### ✅ **4. Mantenible**
Cambios en resoluciones DIAN:
- Actualizar data XML
- No tocar código Python

### ✅ **5. Extensible**
Fácil agregar:
- Nuevos métodos de acumulación
- Nuevos tipos de fuente de datos
- Nuevos formatos

---

## Métodos de Acumulación Disponibles

### `debit`
Suma total de débitos de las cuentas.

**Usar para:**
- Gastos y costos (cuentas 5xxx, 6xxx)
- Activos (cuentas 1xxx en aumento)

**Ejemplo:** Campo "pago" en Formato 1001

---

### `credit`
Suma total de créditos de las cuentas.

**Usar para:**
- Retenciones por pagar (cuentas 2365xx)
- Pasivos (cuentas 2xxx en aumento)
- Ingresos (cuentas 4xxx)

**Ejemplo:** Campo "retp" en Formato 1001

---

### `balance`
Saldo neto (debit - credit).

**Usar para:**
- IVA no descontable llevado a costo
- Saldos mixtos

**Ejemplo:** Campo "ided" en Formato 1001

---

### `tax_base_amount`
Base gravable del impuesto desde `account.move.line.tax_base_amount`.

**Usar para:**
- Reportes de IVA
- Bases de retención

---

### `tax_amount`
Valor del impuesto desde `account.move.line.tax_amount`.

**Usar para:**
- IVA generado/descontado
- Retenciones calculadas automáticamente

---

### `closing_balance`
Saldo acumulado hasta fecha de corte, considerando naturaleza de cuenta.

**Usar para:**
- Reportes de saldo (no movimiento)
- Cuentas de balance

**Lógica:**
```python
if account_type in ('asset_*'):
    closing_balance = debit - credit
elif account_type in ('liability_*'):
    closing_balance = credit - debit
```

---

## Ejemplo Completo: Transacción en Odoo → Reporte

### Transacción Contable
```
Fecha: 2025-06-15
Partner: PROVEEDOR S.A.S. (NIT 900123456-7)
Concepto: Honorarios profesionales

Cuenta 511010 (Honorarios)       DÉBITO  1,000,000
Cuenta 236505 (Retención Renta)  CRÉDITO    11,000
Cuenta 111005 (Bancos)            CRÉDITO   989,000
```

### Configuración Formato 1001

**Campo "pago" (Concepto 5002 - Honorarios):**
- Cuenta: 511010
- Método: `debit`

**Campo "retp" (Concepto 5002 - Honorarios):**
- Cuenta: 236505
- Método: `credit`

### Resultado en Reporte

| cpt  | tdoc | nid       | dv | raz              | pago    | retp  |
|------|------|-----------|----|------------------|---------|-------|
| 5002 | 31   | 900123456 | 7  | PROVEEDOR S.A.S. | 1000000 | 11000 |

---

## Resolución de Problemas Comunes

### ❌ Problema: "No aparecen datos en el reporte"

**Causas:**
1. Cuentas no configuradas en `field_account_ids`
2. Rango de fechas incorrecto
3. Movimientos no en estado 'posted'
4. Partners excluidos en configuración

**Solución:**
```python
# Verificar configuración
setting_line = env['l10n_co.exogenous_format_setting_line'].browse(X)
field_accounts = setting_line.format_field_id.field_account_ids

for fa in field_accounts:
    print(f"Concepto: {fa.concept_id.code}")
    print(f"Método: {fa.name}")
    print(f"Cuentas: {fa.account_ids.mapped('code')}")
```

---

### ❌ Problema: "Los valores no cuadran con contabilidad"

**Causas:**
1. Método de acumulación incorrecto
2. Cuentas duplicadas en múltiples conceptos
3. Filtro de diarios aplicado

**Solución:**
- Validar método: ¿debit o credit?
- Verificar que una cuenta solo esté en un concepto
- Revisar `journal_ids` excluidos

---

### ❌ Problema: "Duplicate key value violates unique constraint"

**Causa:**
Configuración duplicada: mismo campo + concepto + método

**Solución:**
```sql
-- Buscar duplicados
SELECT format_field_id, concept_id, name, COUNT(*)
FROM l10n_co_exogenous_format_field_account
GROUP BY format_field_id, concept_id, name
HAVING COUNT(*) > 1;
```

---

## Conclusión

✅ **El enfoque es CORRECTO y está BIEN IMPLEMENTADO**

La arquitectura separa claramente configuración de lógica, permitiendo:
- Fácil mantenimiento
- Alta flexibilidad
- Reutilización de código
- Adaptación a cambios normativos

**Recomendación:** Continuar con este enfoque para todos los formatos DIAN.

---

## Próximos Pasos

1. ✅ Completar configuración XML del Formato 1001 con todos los campos
2. ✅ Crear conceptos DIAN en data XML
3. ✅ Configurar cuentas contables por concepto
4. ⏳ Probar generación de reporte con datos reales
5. ⏳ Validar estructura XML contra esquema DIAN
6. ⏳ Implementar validaciones adicionales (ej: montos mínimos)

---

**Documento actualizado:** 2026-01-21  
**Autor:** Arquitectura validada por GitHub Copilot  
**Versión:** 1.0
