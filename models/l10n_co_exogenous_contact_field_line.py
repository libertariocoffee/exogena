import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class L10nCoExogenousContactFieldLine(models.Model):
    _name = "l10n_co.exogenous_contact_field_line"
    _description = "Línea de Mapeo de Campo de Contacto"
    _order = 'contact_field_id, field_format_id, id'

    # Fields
    contact_field_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_contact_field',
        string='Configuración de Campo de Contacto',
        required=True,
        ondelete='cascade',
        index=True,
    )
    field_format_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_format_field',
        string='Campo de Formato',
        required=True,
        ondelete='restrict',
        help="Campo de formato exógeno a mapear",
    )
    field_odoo_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Campo de Contacto de Odoo',
        required=True,
        domain="[('model', '=', 'res.partner'), ('ttype', 'not in', ('one2many', 'many2many'))]",
        ondelete='set null',
        help="Campo fuente de Odoo del modelo res.partner",
    )
    field_odoo_internal_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Campo Relacionado',
        domain="[('model', '=', relation), ('ttype', 'not in', ('many2one', 'one2many', 'many2many'))]",
        ondelete='set null',
        help="Para campos Many2one, especificar qué campo del modelo relacionado usar",
    )

    # Related fields for domain computation
    ttype = fields.Selection(
        related='field_odoo_id.ttype',
        string='Tipo de Campo',
        store=True,
        readonly=True,
    )
    relation = fields.Char(
        related='field_odoo_id.relation',
        string='Modelo Relacionado',
        store=True,
        readonly=True,
    )
