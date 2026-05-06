import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class L10nCoExogenousFormatField(models.Model):
    _name = "l10n_co.exogenous_format_field"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Definición de Campo de Formato Exógeno"
    _order = 'sequence, id'
    _rec_names_search = ['name', 'attribute']

    # Selection methods
    @api.model
    def _selection_source(self):
        """Get available data sources for format fields."""
        return [
            ('contact', _('Contacto')),
            ('journal_items', _('Apuntes Contables')),
            ('resolution', _('Resolución')),
        ]

    # Fields
    name = fields.Text(
        string='Nombre del Campo',
        required=True,
        tracking=True,
        help="Nombre del campo como aparecerá en el encabezado del reporte",
    )
    sequence = fields.Integer(
        string='Secuencia',
        default=10,
        help="Orden de aparición en el reporte",
    )
    max_length = fields.Integer(
        string='Longitud Máxima',
        tracking=True,
        help="Longitud máxima para el valor del campo en el reporte",
    )
    attribute = fields.Char(
        string='Código del Atributo',
        tracking=True,
        index=True,
        help="Identificador técnico del campo",
    )
    source = fields.Selection(
        selection='_selection_source',
        string='Fuente de Datos',
        required=True,
        tracking=True,
        help="Origen de los datos para este campo",
    )
    format_ids = fields.Many2many(
        comodel_name="l10n_co.exogenous_format",
        relation="l10n_co_exogenous_format_field_rel",
        column1="field_id",
        column2="format_id",
        string='Formatos',
        tracking=True,
    )
    applies_to_company = fields.Boolean(
        string='Aplica a Empresas',
        default=True,
        help="Si está marcado, este campo aplica cuando el contacto es una empresa "
             "(ej. razón social, dígito de verificación)",
    )
    applies_to_contact = fields.Boolean(
        string='Aplica a Personas Naturales',
        default=True,
        help="Si está marcado, este campo aplica cuando el contacto es una persona natural "
             "(ej. primer nombre, apellidos)",
    )
    is_unique_key = fields.Boolean(
        string='Es Llave Única',
        default=False,
        help="Si está marcado, este campo se usa para agrupar y agregar datos del reporte (forma parte de la clave única)",
    )
    format_applies_concepts = fields.Boolean(
        string='El Formato Aplica Conceptos',
        default=True,
        help="Si está marcado, el formato usa conceptos DIAN para organizar los datos",
    )
    format_applies_taxes = fields.Boolean(
        string='El Formato Aplica Impuestos',
        default=False,
        help="Si está marcado, el formato incluye cálculos específicos de impuestos",
    )

    # Odoo field mapping
    field_odoo_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Campo de Odoo',
        ondelete='set null',
        domain="[('model', '=', 'res.partner'), ('ttype', 'not in', ('one2many', 'many2many'))]",
        help="Campo del partner de Odoo a mapear a este campo del reporte",
    )
    ttype = fields.Selection(
        related='field_odoo_id.ttype',
        string='Tipo de Campo',
        readonly=True,
        store=True,
    )
    relation = fields.Char(
        related='field_odoo_id.relation',
        string='Modelo Relacionado',
        readonly=True,
        store=True,
    )
    field_odoo_internal_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Campo Relacionado',
        ondelete='set null',
        domain="[('model', '=', relation), ('ttype', 'not in', ('many2one', 'one2many', 'many2many'))]",
        help="Para campos Many2one, especificar qué campo del modelo relacionado mostrar",
    )

    # Account configuration
    field_account_ids = fields.One2many(
        comodel_name='l10n_co.exogenous_format_field_account',
        inverse_name='format_field_id',
        string='Configuraciones de Cuenta',
        help="Mapeos de cuentas y conceptos para este campo",
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