import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class L10nCoExogenousDocumentType(models.Model):
    _name = "l10n_co.exogenous_document_type"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Mapeo de Tipos de Documentos para Exógena"
    _rec_names_search = ['name', 'code']

    # SQL constraint for better performance
    _sql_constraints = [
        ('unique_code_company', 'UNIQUE(code, company_id)',
         '¡El código DIAN debe ser único por compañía!'),
    ]

    # Fields
    name = fields.Char(
        string='Nombre',
        required=True,
        tracking=True,
        index=True,
    )
    code = fields.Char(
        string='Código DIAN',
        required=True,
        size=2,
        tracking=True,
        index=True,
        help="Código oficial DIAN para este tipo de documento (2 dígitos)",
    )
    type_document_ids = fields.Many2many(
        comodel_name='l10n_latam.identification.type',
        relation='l10n_co_exogenous_doc_type_id_type_rel',
        column1='exogenous_doc_type_id',
        column2='identification_type_id',
        string='Tipos de Identificación Odoo',
        required=True,
        tracking=True,
        help="Tipos de identificación de Odoo que se mapean a este código DIAN.\n"
             "Ejemplo: 'NIT de otro país' puede mapear a NIT extranjero, NIUP, IVA, RUC, etc.",
    )
    document_type_table_ids = fields.Many2many(
        comodel_name="l10n_co.exogenous_document_type_table",
        relation="l10n_co_exogenous_document_type_table_rel",
        column1="document_type_id",
        column2="document_type_table_id",
        string='Tablas de Tipos de Documentos',
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