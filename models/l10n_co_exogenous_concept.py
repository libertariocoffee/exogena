import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class L10nCoExogenousConcept(models.Model):
    _name = "l10n_co.exogenous_concept"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Concepto de Información Exógena"
    _rec_name = 'code'
    _rec_names_search = ['name', 'code']
    _order = 'code, id'

    # SQL constraint for better performance
    _sql_constraints = [
        ('unique_code_format_company', 'UNIQUE(code, format_id, company_id)',
         '¡El código debe ser único por formato y compañía!'),
    ]

    # Fields
    name = fields.Text(
        string='Nombre',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Código del Concepto',
        required=True,
        size=4,
        tracking=True,
        index=True,
        help="Código del concepto DIAN (4 dígitos)",
    )
    format_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_format',
        string='Formato',
        required=True,
        tracking=True,
        ondelete='cascade',
        index=True,
    )
    report_with_informan_nit = fields.Boolean(
        string="Reportar con NIT del Informante",
        default=False,
        help="Incluir el NIT del informante en el reporte para este concepto",
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company.id,
        ondelete='restrict',
        index=True,
    )

    # Methods
    def name_get(self):
        """Return formatted name with code prefix."""
        result = []
        for rec in self:
            concept_name = rec.name
            if len(concept_name) > 100:
                concept_name = concept_name[:100] + '...'
            name = f'[{rec.code}] {concept_name}'
            result.append((rec.id, name))
        return result