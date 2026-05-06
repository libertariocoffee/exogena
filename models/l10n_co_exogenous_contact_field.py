import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class L10nCoExogenousContactField(models.Model):
    _name = "l10n_co.exogenous_contact_field"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Configuración de Mapeo de Campos de Contacto"
    _rec_name = 'company_id'

    # SQL constraint for one configuration per company
    _sql_constraints = [
        ('unique_company', 'UNIQUE(company_id)',
         '¡Solo se permite una configuración de campos de contacto por compañía!'),
    ]

    # Fields
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company.id,
        ondelete='restrict',
        index=True,
    )
    field_line_ids = fields.One2many(
        comodel_name='l10n_co.exogenous_contact_field_line',
        inverse_name='contact_field_id',
        string='Mapeo de Campos',
        help="Define cómo los campos del partner se mapean a los campos del reporte exógeno",
    )
