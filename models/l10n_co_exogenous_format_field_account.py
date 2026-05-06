import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class L10nCoExogenousFormatFieldAccount(models.Model):
    _name = "l10n_co.exogenous_format_field_account"
    _description = "Configuración de Cuenta de Campo de Formato"
    _order = 'format_field_id, concept_id, id'
    _rec_name = 'format_field_id'

    # SQL constraint to prevent duplicate configurations
    _sql_constraints = [
        ('unique_field_concept_method', 
         'UNIQUE(format_field_id, concept_id, name)',
         '¡Ya existe una configuración para este campo, concepto y método de acumulación!'),
    ]

    # Selection methods
    @api.model
    def _selection_accumulated_by(self):
        """Get available accumulation methods for account values.
        
        These methods define how account values are accumulated:
        - balance: Net balance (debit - credit) for the period
        - credit: Total credits for the period
        - debit: Total debits for the period
        - tax_base_amount: Tax base from account.move.line
        - closing_balance: Cumulative balance up to the cutoff date
        - tax_amount: Tax amount from account.move.line (for tax-based fields)
        """
        return [
            ('balance', _('Saldo (Neto)')),
            ('credit', _('Crédito')),
            ('debit', _('Débito')),
            ('tax_base_amount', _('Base Gravable')),
            ('tax_amount', _('Valor del Impuesto')),
            ('closing_balance', _('Saldo de Cierre')),
        ]

    # Fields
    format_field_id = fields.Many2one(
        comodel_name="l10n_co.exogenous_format_field",
        string='Campo de Formato',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Selection(
        selection='_selection_accumulated_by',
        string='Método de Acumulación',
        required=True,
        default='balance',
        help="Método de acumulación de valores contables:\n"
             "• Balance: Saldo neto (débito - crédito) del período\n"
             "• Crédito: Total de créditos del período\n"
             "• Débito: Total de débitos del período\n"
             "• Base Gravable: Base del impuesto desde account.move.line\n"
             "• Valor del Impuesto: Monto del impuesto desde account.move.line\n"
             "• Saldo de Cierre: Saldo acumulado hasta la fecha de corte\n\n"
             "Para Formato 1001, ejemplos de uso:\n"
             "• 'pago': usar Débito/Crédito según naturaleza de la cuenta\n"
             "• 'retp': usar Crédito para cuentas de retención\n"
             "• 'ided': usar Balance para cuentas de IVA no descontable",
    )
    account_ids = fields.Many2many(
        comodel_name='account.account',
        string='Cuentas',
        required=True,
        domain="[('deprecated', '=', False)]",
        help="Plan de cuentas a incluir para el cálculo de este campo.\n\n"
             "Para Formato 1001, ejemplos:\n"
             "• Campo 'pago': cuentas de costos/gastos deducibles (51xx, 52xx)\n"
             "• Campo 'pnded': cuentas de gastos no deducibles\n"
             "• Campo 'retp': cuentas de retención en la fuente por pagar (2365xx)\n"
             "• Campo 'ided': cuentas de IVA llevado como mayor valor del costo",
    )
    taxes_ids = fields.Many2many(
        comodel_name='account.tax',
        string='Impuestos',
        domain="[('type_tax_use', '=', 'purchase'), ('name', 'ilike', 'IVA%')]",
        help="Filtros de impuestos para reportes basados en impuestos",
    )
    concept_id = fields.Many2one(
        comodel_name="l10n_co.exogenous_concept",
        string='Concepto',
        ondelete='restrict',
        help="Concepto DIAN para agrupación (solo si el formato aplica conceptos)",
    )

    # Computed fields
    format_applies_concepts = fields.Boolean(
        string='El Formato Aplica Conceptos',
        compute='_compute_format_applies_concepts',
        store=True,
        readonly=True,
    )
    format_applies_taxes = fields.Boolean(
        string='El Formato Aplica Impuestos',
        related='format_field_id.format_applies_taxes',
        store=True,
        readonly=True,
    )

    # Compute methods
    @api.depends('format_field_id.source', 'format_field_id.format_applies_concepts')
    def _compute_format_applies_concepts(self):
        """Compute if format applies concepts based on source and format configuration."""
        for rec in self:
            rec.format_applies_concepts = (
                rec.format_field_id.source == 'journal_items' and
                rec.format_field_id.format_applies_concepts
            )

