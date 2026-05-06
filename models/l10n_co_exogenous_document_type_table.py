import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class L10nCoExogenousDocumentTypeTable(models.Model):
    _name = "l10n_co.exogenous_document_type_table"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Tabla de Tipos de Documentos para Exógena"
    _rec_names_search = ['name']

    # SQL constraint for better performance
    _sql_constraints = [
        ('unique_name_company', 'UNIQUE(name, company_id)',
         '¡El nombre debe ser único por compañía!'),
    ]

    # Fields
    name = fields.Char(
        string='Nombre',
        required=True,
        tracking=True,
        index=True,
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