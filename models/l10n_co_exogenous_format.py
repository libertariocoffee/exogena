import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class L10nCoExogenousFormat(models.Model):
    _name = "l10n_co.exogenous_format"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Formato de Información Exógena DIAN"
    _rec_name = 'code'
    _rec_names_search = ['name', 'code']
    _order = 'code, id'

    # SQL constraint for better performance
    _sql_constraints = [
        ('unique_code_company', 'UNIQUE(code, company_id)',
         '¡El código del formato debe ser único por compañía!'),
    ]

    # Fields
    name = fields.Char(
        string='Nombre',
        required=True,
        tracking=True,
        index=True,
    )
    code = fields.Char(
        string='Código del Formato',
        required=True,
        size=4,
        tracking=True,
        index=True,
        help="Código del formato DIAN (ej. 1001, 1003, etc.)",
    )
    version = fields.Char(
        string='Versión',
        tracking=True,
        help="Número de versión del formato",
    )
    appendix = fields.Char(
        string='Anexo',
        tracking=True,
        help="Identificador del anexo del formato",
    )
    document_type_table_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_document_type_table',
        string='Tabla de Tipos de Documentos',
        tracking=True,
        ondelete='restrict',
        help="Tabla de mapeo de tipos de documentos a usar para este formato",
    )
    is_it_with_date_range = fields.Boolean(
        string='Usa Rango de Fechas',
        default=True,
        help="Si está marcado, el reporte filtrará datos por rango de fechas (movimiento). Si no, reporta saldo a corte (31 de diciembre)",
    )
    apply_concepts = fields.Boolean(
        string='Aplica Conceptos',
        default=False,
        help="Si está marcado, el formato usa conceptos DIAN para agrupar",
    )
    applying_smaller_amounts = fields.Boolean(
        string='Aplica Agrupación por Cuantías Menores',
        default=False,
        help="Si está marcado, los montos por debajo del umbral se agruparán en una sola línea con NIT 222222222 (Tipo Doc 43)",
    )
    smaller_ammounts = fields.Monetary(
        string='Umbral de Cuantías Menores',
        currency_field='company_currency_id',
        default=0.0,
        help="Los montos por debajo de este umbral se agregarán bajo un registro genérico de cuantías menores",
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
    company_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Moneda de la Compañía',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )

    # Methods
    def name_get(self):
        """Return formatted name with code prefix."""
        result = []
        for rec in self:
            name_format = rec.name
            if len(name_format) > 100:
                name_format = name_format[:100] + '...'
            name = f'[{rec.code}] {name_format}'
            result.append((rec.id, name))
        return result

