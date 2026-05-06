import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class L10nCoExogenousFormatSettingLine(models.Model):
    _name = "l10n_co.exogenous_format_setting_line"
    _description = "Línea de Configuración de Formato - Activación de Campos"
    _order = 'format_setting_id, sequence, id'

    # Fields
    format_setting_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_format_setting',
        string='Configuración del Formato',
        required=True,
        ondelete='cascade',
        index=True,
    )
    format_field_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_format_field',
        string='Campo del Formato',
        required=True,
        ondelete='restrict',
        help="Campo del formato a incluir en el reporte",
    )
    sequence = fields.Integer(
        related='format_field_id.sequence',
        string='Secuencia',
        store=True,
        readonly=True,
    )

    # Related fields
    apply_concepts = fields.Boolean(
        string='Aplica Conceptos',
        related='format_setting_id.apply_concepts',
        store=True,
        readonly=True,
    )