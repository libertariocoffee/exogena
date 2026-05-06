import base64
import io
import logging
import operator
from datetime import date, datetime, timedelta
from functools import reduce

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

from odoo.addons.l10n_co_exogenous_information_reporting.tools.utils import (
    _check_dv,
    _column_name_field,
    dian_countries_codes,
    dian_department_codes,
)

_logger = logging.getLogger(__name__)


class L10nCoExogenousFormatSetting(models.Model):
    _name = "l10n_co.exogenous_format_setting"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Configuración de Reporte Exógeno"
    _rec_name = 'format_id'
    _order = 'date_start desc, format_id, id'

    # =============================================================================================
    #                                          CONSTRAINTS
    # =============================================================================================

    def _check_dates(self):
        """Validate date range configuration.

        This validation is only performed when generating the report, not during record creation/editing.
        """
        for record in self:
            if not record.is_it_with_date_range:
                continue

            if not record.date_start or not record.date_end:
                raise ValidationError(
                    _("La fecha inicial y la fecha final son requeridas cuando se usa rango de fechas"))

            if record.date_start > record.date_end:
                raise ValidationError(
                    _("La fecha inicial debe ser anterior a la fecha final"))

            if record.date_start.year != record.date_end.year:
                raise ValidationError(
                    _("La fecha inicial y la fecha final deben estar en el mismo año fiscal"))

    # =============================================================================================
    #                                            FIELDS
    # =============================================================================================

    # === Configuration ===
    format_id = fields.Many2one(
        comodel_name='l10n_co.exogenous_format',
        string='Formato',
        required=True,
        tracking=True,
        ondelete='restrict',
        index=True,
        help="Formato exógeno DIAN a generar",
    )
    format_setting_line_ids = fields.One2many(
        comodel_name='l10n_co.exogenous_format_setting_line',
        inverse_name='format_setting_id',
        string='Campos del Formato',
        help="Campos a incluir en el reporte",
    )
    apply_concepts = fields.Boolean(
        string='Aplica Conceptos',
        related='format_id.apply_concepts',
        store=True,
        readonly=True,
    )
    is_it_with_date_range = fields.Boolean(
        string='Usa Rango de Fechas',
        related='format_id.is_it_with_date_range',
        store=True,
        readonly=True,
    )

    # === Filters ===
    date_start = fields.Date(
        string='Fecha Inicial',
        tracking=True,
        help="Fecha de inicio del reporte (requerida si el formato usa rango de fechas)",
    )
    date_end = fields.Date(
        string='Fecha Final',
        tracking=True,
        help="Fecha final del reporte (requerida si el formato usa rango de fechas)",
    )
    journal_ids = fields.Many2many(
        comodel_name='account.journal',
        string='Diarios Excluidos',
        help="Los asientos de estos diarios se excluirán del reporte",
    )
    partner_ids = fields.Many2many(
        comodel_name='res.partner',
        string='Contactos Excluidos',
        help="Las transacciones con estos contactos se excluirán del reporte",
    )

    # === Configuración de Cuantías Menores ===
    smaller_amount_document_type = fields.Char(
        string='Tipo Documento Cuantías Menores',
        default='43',
        help="Código del tipo de documento para agregación de cuantías menores (ej. '43' para NIT extranjero)",
    )
    smaller_amount_nit = fields.Char(
        string='NIT Cuantías Menores',
        default='222222222',
        help="NIT a usar para la línea de agregación de cuantías menores",
    )
    smaller_amount_name = fields.Char(
        string='Nombre Cuantías Menores',
        default='Cuantías menores',
        help="Nombre a mostrar para la línea de agregación de cuantías menores",
    )

    # === Configuración de Transacciones sin Tercero ===
    no_partner_name = fields.Char(
        string='Nombre Transacciones sin Tercero',
        default='Movimientos sin terceros',
        help="Nombre a mostrar para transacciones sin contacto asociado",
    )

    # === Configuración de Cálculo de Saldo ===
    closing_balance_method = fields.Selection([
        ('asset_liability', 'Basado en Tipo Activo/Pasivo (Recomendado)'),
        ('account_prefix', 'Basado en Prefijo del Código de Cuenta'),
    ],
        default='asset_liability',
        string='Método de Cálculo del Saldo de Cierre',
        required=True,
        help="Cómo determinar la naturaleza débito vs crédito para cálculos de saldo de cierre:\n"
             "- Activo/Pasivo: Usa el tipo de cuenta de Odoo (activo = débito-crédito, pasivo = crédito-débito)\n"
             "- Prefijo de Cuenta: Usa prefijos de códigos de cuenta (legado, menos flexible)",
    )
    asset_account_prefixes = fields.Char(
        string='Prefijos de Cuentas de Activo',
        default='1',
        help="Prefijos separados por coma para cuentas de activo (ej. '1,14,15'). "
             "Solo se usa cuando el método es 'prefijo de cuenta'",
    )
    liability_account_prefixes = fields.Char(
        string='Prefijos de Cuentas de Pasivo',
        default='2,3,4,5,6',
        help="Prefijos separados por coma para cuentas de pasivo. "
             "Solo se usa cuando el método es 'prefijo de cuenta'",
    )


    # === Output ===
    binary_file = fields.Binary(
        string='Archivo Generado',
        readonly=True,
        attachment=True,
    )
    binary_file_name = fields.Char(
        string='Nombre del Archivo',
        readonly=True,
        tracking=True,
    )

    # === General ===
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

    # =============================================================================================
    #                                     VALIDATION METHODS
    # =============================================================================================

    def _validate_report_configuration(self):
        """Validate configuration before generating report.

        Raises:
            UserError: If configuration is incomplete or invalid
        """
        self.ensure_one()

        if not self.format_setting_line_ids:
            raise UserError(
                _("No se han configurado campos de formato para el formato: %s", self.format_id.code))

        if self.is_it_with_date_range:
            if not self.date_start or not self.date_end:
                raise UserError(
                    _("El rango de fechas es requerido para este formato"))

    # =============================================================================================
    #                                     CACHE METHODS
    # =============================================================================================

    def _get_format_field_ref(self, code):
        """Get format field reference by code.

        Uses env.ref() which already has internal caching via ir.model.data,
        making additional caching unnecessary and potentially problematic
        (caching recordsets can cause cursor/environment issues).

        Args:
            code (str): Field code (e.g., 'tdoc', 'nid', 'raz', 'dv', 'dpto', 'pais', 'cpt')

        Returns:
            recordset: Format field record or empty recordset if not found
        """
        return self.env.ref(
            f'l10n_co_exogenous_information_reporting.l10n_co_exogenous_format_field_{code}',
            raise_if_not_found=False
        ) or self.env['l10n_co.exogenous_format_field']

    def _get_nit_document_code(self):
        """Get NIT document type code dynamically from configuration.
        
        Searches for the NIT/RUT document type in the system and returns
        its mapped code for the current format. Falls back to '31' if not found.
        
        Returns:
            str: Document type code for NIT (default: '31')
        """
        # Buscar tipo de documento NIT/RUT
        nit_type = self.env['l10n_latam.identification.type'].search([
            ('l10n_co_document_code', '=', 'rut')
        ], limit=1)

        if not nit_type:
            _logger.warning("NIT type not found, using fallback '31'")
            return '31'

        # Obtener mapeo para este formato
        if self.format_id.document_type_table_id:
            mapping = self.env['l10n_co.exogenous_document_type'].search([
                ('type_document_ids', 'in', [nit_type.id]),
                ('document_type_table_ids', 'in', self.format_id.document_type_table_id.id)
            ], limit=1)

            if mapping:
                return mapping.code

        return '31'  # Fallback

    # =============================================================================================
    #                                     HELPER METHODS
    # =============================================================================================
    
    def _get_fields_many2one(self, fields_contact):
        """
            Función que nos permite obtener de los campo de Odoo de contacto cuales son de tipo Many2one
        """
        return fields_contact.mapped('field_odoo_id').filtered(lambda field: field.ttype == 'many2one')

    def _get_closing_balance_cutoff_date(self):
        """Get the cutoff date for closing balance calculations.

        For closing balance reports (like format 1008, 1009), this returns
        the last day of the reporting year (December 31st of date_end's year).

        If date_end is not set, falls back to December 31st of the previous year.

        Returns:
            date: Cutoff date for closing balance calculations
        """
        if self.date_end:
            # Use the last day of the reporting year (Dec 31 of date_end's year)
            return date(self.date_end.year, 12, 31)
        # Fallback: last day of previous year
        return date(date.today().year - 1, 12, 31)

    def _get_type_documents_by_format(self):
        """Get document type mappings for the current format from DIAN configuration."""
        return self.env['l10n_co.exogenous_document_type'].search_read(
            domain=[
                ('document_type_table_ids', 'in', self.format_id.document_type_table_id.id),
                ('type_document_ids', '!=', False),
            ],
            fields=['type_document_ids', 'code'],
        )

    def _get_columns_account_move_line_by_format(self):
        fields_use_account_move_line = self._get_fields_use_account_move_line()
        return fields_use_account_move_line + ['date', 'partner_id', 'account_id','move_id']

    def _get_accounts_by_format(self):
        vals = {}
        for setting_line in self.format_setting_line_ids:
            if self.format_id.apply_concepts:
                for field_account in setting_line.format_field_id.field_account_ids:
                    for account in field_account.account_ids:
                        if account.id not in vals:
                            vals[account.id] = field_account.concept_id.code
            else:
                for account in setting_line.format_field_id.field_account_ids.account_ids:
                    if account.id not in vals:
                        vals[account.id] = setting_line.format_field_id.id

        return vals

    def _normalize_partner_dataframe(self, fields_many2one, df_partners, df_type_documents, df_other_info, fields_to_clear_contact, fields_to_clear_company):
        """Normalize partner data in dataframe.

        Args:
            fields_many2one (dict): Many2one field mappings
            df_partners (pd.DataFrame): Partner data dataframe
            df_type_documents (pd.DataFrame): Document type mappings
            df_other_info (pd.DataFrame): Additional related data
            fields_to_clear_contact (list): Fields to clear for natural persons
            fields_to_clear_company (list): Fields to clear for companies

        Returns:
            pd.DataFrame: Normalized partner dataframe
        """
        # Build mapping dict for Many2many: each identification type ID maps to its DIAN code
        # This MUST be done BEFORE processing other Many2one fields, because we need the ID
        # type_document_ids from search_read is a list of IDs: [id1, id2, id3, ...]
        type_doc_mapping_dict = {}
        for _, doc_type in df_type_documents.iterrows():
            code = doc_type['code']
            # type_document_ids is a list of integer IDs
            type_ids = doc_type['type_document_ids']
            _logger.info("Processing doc_type with code %s, type_ids: %s (type: %s)",
                        code, type_ids, type(type_ids))

            # Handle different possible formats
            if isinstance(type_ids, list):
                for type_id in type_ids:
                    # Map ID to DIAN code
                    type_doc_mapping_dict[type_id] = code
                    _logger.info("  Mapped type_id %s to code %s", type_id, code)
            else:
                _logger.warning("  type_document_ids is not a list: %s", type_ids)

        _logger.info("Final type_doc_mapping_dict: %s", type_doc_mapping_dict)

        # Map identification type to DIAN code BEFORE other Many2one processing
        # In df_partners, l10n_latam_identification_type_id comes as tuple (id, 'Name')
        # We use the ID (position 0) to look up the DIAN code
        if 'l10n_latam_identification_type_id' in df_partners.columns:
            def map_type_to_code(x):
                if isinstance(x, (list, tuple)):
                    type_id = x[0]
                    type_name = x[1] if len(x) > 1 else 'Unknown'
                else:
                    type_id = x
                    type_name = str(x)

                result = type_doc_mapping_dict.get(type_id, x)
                if result == x:
                    _logger.warning("No DIAN code mapping found for identification type ID: %s (Name: %s)",
                                  type_id, type_name)
                return result

            df_partners['l10n_latam_identification_type_id'] = df_partners['l10n_latam_identification_type_id'].apply(map_type_to_code)

        # Process other Many2one fields (excluding l10n_latam_identification_type_id which was already processed)
        for key, value in fields_many2one.items():
            # Skip l10n_latam_identification_type_id as it was already mapped above
            if key == 'l10n_latam_identification_type_id':
                continue

            if key in df_partners.columns and key in df_other_info.columns:
                mapping_dict = {d['id']: d.get(
                    value, None) for element in df_other_info[key] for d in element}
                df_partners[key] = df_partners[key].apply(
                    lambda x: mapping_dict.get(x[0] if isinstance(x, (list, tuple)) else x, x))

        # Vectorized approach instead of iterrows() - much faster
        # Clear fields for companies (is_company == True)
        if fields_to_clear_company:
            company_mask = df_partners['is_company'] == True
            valid_cols = [col for col in fields_to_clear_company if col in df_partners.columns]
            if valid_cols:
                df_partners.loc[company_mask, valid_cols] = None

        # Clear fields for contacts (is_company == False)
        if fields_to_clear_contact:
            contact_mask = df_partners['is_company'] == False
            valid_cols = [col for col in fields_to_clear_contact if col in df_partners.columns]
            if valid_cols:
                df_partners.loc[contact_mask, valid_cols] = None

        return df_partners

    def _normalize_and_merge_account_move_lines(self, df_account_move_lines, df_partners):
        """Normalize and merge account move lines with partner data.

        Args:
            df_account_move_lines (pd.DataFrame): Account move line data
            df_partners (pd.DataFrame): Normalized partner data

        Returns:
            pd.DataFrame: Merged dataframe with partner and accounting data
        """
        # Extract partner ID from tuple (id, name) - vectorized
        df_account_move_lines = df_account_move_lines.copy()
        df_account_move_lines['partner_id'] = df_account_move_lines['partner_id'].str[0]

        # Merge based on partner_id and id columns
        df_result = pd.merge(
            df_account_move_lines,
            df_partners,
            left_on='partner_id',
            right_on='id',
            how='left',
            suffixes=('', '_partner'),
        )

        # Drop unnecessary columns in a single operation (avoiding inplace=True deprecation)
        columns_to_drop = ['id_partner', 'id', 'partner_id']
        columns_to_drop = [col for col in columns_to_drop if col in df_result.columns]
        if columns_to_drop:
            df_result = df_result.drop(columns=columns_to_drop)

        return df_result

    def _get_field_name_second_field_many2one(self, fields_contact):
        """Get mapping of Many2one field names to their internal field names.

        Returns:
            dict: Mapping of field_odoo_id.name to field_odoo_internal_id.name(s)
        """
        vals = {}
        for field in fields_contact.filtered(lambda f: f.ttype == 'many2one'):
            field_name = field.field_odoo_id.name
            internal_name = field.field_odoo_internal_id.name
            if field_name not in vals:
                vals[field_name] = internal_name
            else:
                # Convert to list if not already and append
                existing = vals[field_name]
                if isinstance(existing, list):
                    existing.append(internal_name)
                else:
                    vals[field_name] = [existing, internal_name]
        return vals

    # Sentinel tuple stored on tax_amount-aggregated rows so the truthiness
    # check in _select_fields_from_account_move_line keeps working without
    # a special-case branch. Real tax_line_id values from search_read are
    # tuples (id, display_name); we never collide with id=-1.
    _TAX_AMOUNT_SENTINEL = (-1, '_aggregated_tax_lines')

    def _read_group_account_move_lines(self, field_account, *, extra_domain=None,
                                       include_no_partner=True):
        """Aggregate account.move.line rows by (account_id, partner_id) at DB level.

        Returns a uniform shape regardless of accumulation method, replacing the old
        search_read path that materialized every individual line into Python.

        Args:
            field_account: Field account configuration with account_ids.
            extra_domain: Additional domain leaves (typically date range or tax-line
                filter). Caller is responsible for date semantics.
            include_no_partner: If False, rows aggregated under partner_id IS NULL
                are dropped. closing_balance uses False to preserve historical
                behavior; other methods use True so the "Movimientos sin terceros"
                row downstream gets populated.

        Returns:
            tuple: (partner_ids: set[int], lines: list[dict]) where each dict has
                {account_id: (id, name), partner_id: (id, name) | False,
                 balance, debit, credit, tax_base_amount, tax_amount, tax_line_id}.
        """
        domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('account_id', 'in', field_account.account_ids.ids),
        ]
        if extra_domain:
            domain += list(extra_domain)
        if self.journal_ids:
            domain.append(('journal_id', 'not in', self.journal_ids.ids))
        if self.partner_ids:
            domain.append(('partner_id', 'not in', self.partner_ids.ids))

        results = self.env['account.move.line']._read_group(
            domain=domain,
            groupby=['account_id', 'partner_id'],
            aggregates=['balance:sum', 'debit:sum', 'credit:sum', 'tax_base_amount:sum'],
        )

        partner_ids = set()
        account_move_lines = []
        for account, partner, balance_sum, debit_sum, credit_sum, tax_base_sum in results:
            if not partner and not include_no_partner:
                continue
            if partner:
                partner_ids.add(partner.id)
                partner_repr = (partner.id, partner.display_name)
            else:
                partner_repr = False
            account_move_lines.append({
                'account_id': (account.id, account.display_name),
                'partner_id': partner_repr,
                'balance': balance_sum or 0.0,
                'debit': debit_sum or 0.0,
                'credit': credit_sum or 0.0,
                'tax_base_amount': tax_base_sum or 0.0,
                'tax_amount': 0.0,  # populated downstream from |balance| when applicable
                'tax_line_id': False,  # overridden by tax_amount path below
            })
        return partner_ids, account_move_lines

    def _get_closing_balance_by_read_group(self, field_account):
        """Closing balance: cumulative until cutoff date, excludes no-partner rows.

        Kept as a thin wrapper for backward compatibility — historical callers
        (and module overrides) may rely on this entry point. The shape of the
        return is preserved exactly: (partner_ids set, list of dicts).
        """
        return self._read_group_account_move_lines(
            field_account,
            extra_domain=[('date', '<=', self._get_closing_balance_cutoff_date())],
            include_no_partner=False,
        )

    def _get_information_by_account_move_line(self, field_account):
        """Dispatch by accumulation method to the corresponding aggregation strategy.

        All paths now use _read_group at DB level instead of search_read of
        individual move lines. This trades per-line precision (which the
        downstream pipeline immediately groups away anyway) for orders of
        magnitude less Python<->DB traffic.

        Args:
            field_account: Field account configuration.

        Returns:
            list: [partner_ids set, account_move_lines list of dicts].
        """
        method = field_account.name

        if method == 'closing_balance':
            partner_ids, lines = self._get_closing_balance_by_read_group(field_account)
            return [partner_ids, lines]

        # Build the date-range portion of the domain shared by debit/credit/balance/
        # tax_base_amount/tax_amount.
        if self.is_it_with_date_range:
            date_domain = [
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
            ]
        else:
            date_domain = [('date', '<=', self._get_closing_balance_cutoff_date())]

        if method == 'tax_amount':
            # Pre-filter to tax lines so the aggregation only sums tax-line balances.
            # NOTE: this changes per-line abs(balance) summed → abs(SUM(balance)).
            # The two are equivalent when sign within a (account, partner) bucket is
            # constant (the typical case for tax lines). Documented in the changelog.
            partner_ids, lines = self._read_group_account_move_lines(
                field_account,
                extra_domain=date_domain + [('tax_line_id', '!=', False)],
                include_no_partner=True,
            )
            for line in lines:
                line['tax_line_id'] = self._TAX_AMOUNT_SENTINEL
            return [partner_ids, lines]

        # debit, credit, balance, tax_base_amount: standard aggregation.
        partner_ids, lines = self._read_group_account_move_lines(
            field_account, extra_domain=date_domain, include_no_partner=True,
        )
        return [partner_ids, lines]

    def _get_values_form_many2one(self, data_source, fields_many2one):
        """ 
            Funcion que nos permite de acuerdo a una informacion obtenida por un search_read
            y con base a unos campos que son de tipo many2one obtener los ids de esos modelos
            y llevarlos en una lista
        """
        values_fields_many2one = {}
        for ds in data_source:
            for field_many2one in fields_many2one:
                if not isinstance(ds[field_many2one], bool):
                    if field_many2one not in values_fields_many2one:
                        values_fields_many2one[field_many2one] = [
                            ds[field_many2one][0]]
                    else:
                        values_fields_many2one[field_many2one].append(
                            ds[field_many2one][0])
        return values_fields_many2one

    def _get_data_from_dynamic_model(self, partner_info, fields_contact):

        fields_many2one_odoo = self._get_fields_many2one(fields_contact)
        fields_names_many2one_odoo = fields_many2one_odoo.mapped("name")
        values_fields_many2one = self._get_values_form_many2one(
            partner_info, fields_names_many2one_odoo)

        list_fields_name_and_models = fields_contact.mapped('field_odoo_id').filtered(
            lambda field: field.ttype == 'many2one').mapped(lambda field: {field.name: field.relation})
        values_by_dynamic_models = {}

        for dict_field_name_and_model in list_fields_name_and_models:
            for values in dict_field_name_and_model:
                if values_fields_many2one.get(values, False):
                    field_odoo_internal = fields_contact.filtered(
                        lambda field_line: field_line.field_odoo_id.name == values).mapped('field_odoo_internal_id')

                    model = dict_field_name_and_model[values]
                    domain = [
                        ('id', 'in', list(set(values_fields_many2one.get(values))))]
                    fields = field_odoo_internal.mapped('name')
                    search_read_by_dynamic_model = self.env[model].search_read(
                        domain=domain, fields=fields)

                    if values not in values_by_dynamic_models:
                        values_by_dynamic_models[values] = search_read_by_dynamic_model
                    else:
                        values_by_dynamic_models[values].extend(
                            search_read_by_dynamic_model)

        return values_by_dynamic_models

    def _get_information_partner(self, partner_ids, fields_contact):

        if not fields_contact:
            raise UserError(_("No se han configurado campos de contacto para la compañía: %s", self.company_id.name))

        fields_odoo = fields_contact.mapped('field_odoo_id.name')
        fields_odoo.append('is_company')

        model = 'res.partner'
        domain = [('id', 'in', list(partner_ids)), '|', ('active', '=', True), ('active', '=', False)]
        fields = fields_odoo

        partner_info = self.env[model].search_read(domain=domain, fields=fields)

        other_info_contact = self._get_data_from_dynamic_model(
            partner_info, fields_contact)
        return partner_info, other_info_contact

    def _get_field_account(self, format_setting_line):
        return format_setting_line.mapped('format_field_id').mapped('field_account_ids')

    def _get_field_concept(self):
        """Get the concept field reference. Uses _get_format_field_ref for consistency."""
        return self._get_format_field_ref('cpt')

    def _get_columns_ordered(self, format_fields) -> list:
        """Get ordered column names for the format fields."""
        vals = []
        # Cache field_concept outside the loop to avoid repeated env.ref() calls
        field_concept = self._get_field_concept()
        field_concept_id = field_concept.id if field_concept else None

        for format_field in format_fields:
            if field_concept_id and format_field.id == field_concept_id:
                vals.append('account_id')
            elif format_field.field_odoo_id:
                vals.append(format_field.field_odoo_id.name)
        return vals

    def _get_fields_to_clear(self, fields_contact, applies_to_field):
        """Get fields that should be cleared based on applicability.

        Args:
            fields_contact: Contact field recordset
            applies_to_field: Field name to check ('applies_to_contact' or 'applies_to_company')

        Returns:
            list: Field names to clear
        """
        all_field_names = set(fields_contact.mapped('field_odoo_id.name'))
        applicable_fields = fields_contact.filtered(
            lambda f: f.source == 'contact' and getattr(f, applies_to_field, False)
        )
        applicable_field_names = set(applicable_fields.mapped('field_odoo_id.name'))
        return list(all_field_names - applicable_field_names)

    def _get_fields_to_clear_contact(self, fields_contact):
        """Get fields to clear for natural persons (contacts)."""
        return self._get_fields_to_clear(fields_contact, 'applies_to_contact')

    def _get_fields_to_clear_company(self, fields_contact):
        """Get fields to clear for companies."""
        return self._get_fields_to_clear(fields_contact, 'applies_to_company')

    def _format_field_by_accumulated(self, format_setting_line):
        """Build mapping of accounts to accumulation methods for a format field."""
        accounts_accumulated_by = {
            (account.id, account.display_name): field_account.name
            for field_account in format_setting_line.format_field_id.field_account_ids
            for account in field_account.account_ids
        }
        return {format_setting_line.format_field_id.name: accounts_accumulated_by}

    def _get_fields_use_account_move_line(self):
        """Get fields to extract from account.move.line records.

        Returns:
            list: Field names needed for calculations

        Note: tax_amount is computed from balance for tax lines (where tax_line_id is set).
              We don't fetch it directly as it's not a stored field in account.move.line.
        """
        return ['credit', 'debit', 'balance', 'tax_base_amount', 'tax_line_id']

    def _get_fields_format_id(self, format_setting_line):
        return format_setting_line.mapped('format_field_id').mapped('name')

    def _create_original_dataframe(self, format_fields):
        return pd.DataFrame(columns=format_fields.mapped('name'))

    def _get_fields_odoo_and_format(self, fields_contact):
        """Get mapping from Odoo field names to format field names."""
        vals = {
            field_contact.field_odoo_id.name: field_contact.name
            for field_contact in fields_contact
        }
        if self.format_id.apply_concepts:
            field_concept = self._get_field_concept()
            if field_concept:
                vals['account_id'] = field_concept.name
        return vals

    def _clean_dataframe_for_export(self, df, format_field_names=None):
        """Clean dataframe before exporting to Excel.

        DIAN requirements:
        - Campos monetarios deben diligenciarse siempre (nunca vacíos)
        - Si no hay valor, se debe reportar cero (0)
        - Patrón técnico {1,18}: números enteros sin decimales
        - No se aceptan decimales ni signos de puntuación (sin comas, sin puntos)
        - No se permiten valores negativos (usar valor absoluto)
        - Respetar max_length definido en cada campo

        Args:
            df: DataFrame to clean
            format_field_names: List of format field names (optional, for max_length validation)

        Returns:
            Cleaned DataFrame with DIAN-compliant formatting
        """
        df = df.copy()

        # Get max_length configuration for each field
        max_lengths = {}
        if format_field_names:
            format_fields = self.env['l10n_co.exogenous_format_field'].search([
                ('format_ids', 'in', self.format_id.id)
            ])
            max_lengths = {field.name: field.max_length for field in format_fields if field.max_length}

        # Detect ALL numeric columns automatically
        # This includes format fields AND partner fields (DV, phone, etc.)
        numeric_columns = []
        text_columns = []

        for col in df.columns:
            # Check if column is numeric by dtype or content
            dtype = df[col].dtype

            # Check by pandas dtype first (int, float, etc.)
            if pd.api.types.is_numeric_dtype(dtype):
                numeric_columns.append(col)
            else:
                # For object/string columns, check if all non-null values are numeric
                sample = df[col].dropna()
                if len(sample) > 0:
                    try:
                        # Try to convert all values to numeric
                        pd.to_numeric(sample, errors='raise')
                        numeric_columns.append(col)
                    except (ValueError, TypeError):
                        # Contains non-numeric data, treat as text
                        text_columns.append(col)
                else:
                    # Empty column, treat as text
                    text_columns.append(col)

        # Process ALL numeric columns (monetary fields, IDs, phone numbers, etc.)
        for col in numeric_columns:
            if col in df.columns:
                # 1. Coerce to numeric first (handles object dtype mixed with numbers).
                #    pd.to_numeric returns float64 with NaN for unparseable values, which
                #    skips the FutureWarning that fillna() emits on object dtype in
                #    pandas >=2.2 and becomes a hard error in pandas 3.0.
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

                # 2. Convert negatives to absolute (DIAN does not accept negative values).
                df[col] = df[col].abs()

                # 3. Round to remove decimals and convert to integer.
                # DIAN patrón técnico {1,18} = enteros sin decimales.
                df[col] = df[col].round(0).astype('int64')

                # 5. Validate max_length for numeric fields
                # If a number exceeds max_length digits, truncate.
                if col in max_lengths and max_lengths[col]:
                    max_len = max_lengths[col]
                    max_value = int('9' * max_len)  # e.g., max_len=18 -> 999999999999999999

                    # Vectorized truncation via Series.clip — replaces a per-row apply.
                    df[col] = df[col].clip(upper=max_value)

                    # Log warning if any values were truncated
                    truncated_count = int((df[col] == max_value).sum())
                    if truncated_count > 0:
                        _logger.warning(
                            "Field '%s': %d values exceeded max_length (%d digits) and were truncated to %d",
                            col, truncated_count, max_len, max_value
                        )

        # Replace NaN with empty string in text columns
        for col in text_columns:
            df[col] = df[col].fillna('').astype(str)

            # Truncate text fields to max_length using vectorized .str.slice().
            if col in max_lengths and max_lengths[col]:
                max_len = max_lengths[col]
                df[col] = df[col].str.slice(0, max_len)

                truncated_count = int((df[col].str.len() == max_len).sum())
                if truncated_count > 0:
                    _logger.info(
                        "Field '%s': %d text values were truncated to max_length (%d characters)",
                        col, truncated_count, max_len
                    )

        return df

    def _get_fields_fill_smaller_amount(self):
        """Get default values for smaller amounts row - now configurable.

        Returns values for the aggregated "smaller amounts" row in the report.
        All values are now configurable per format setting instead of hardcoded.

        Returns:
            dict: Mapping of field names to default values
        """
        field_tdoc = self._get_format_field_ref('tdoc')
        field_nid = self._get_format_field_ref('nid')
        field_raz = self._get_format_field_ref('raz')

        result = {}

        if field_tdoc:
            result[field_tdoc.name] = self.smaller_amount_document_type
        if field_nid:
            result[field_nid.name] = self.smaller_amount_nit
        if field_raz:
            result[field_raz.name] = self.smaller_amount_name

        return result
    

    def _generate_row_by_smaller_amount(self, row_smaller_amount, df):
        new_row = pd.DataFrame([row_smaller_amount])  # Usar lista para crear el DataFrame
        new_row_columns = df.columns
        new_row = new_row.reindex(columns=new_row_columns, fill_value=0)  # Fill missing columns with 0

        # Reemplazar append() con pd.concat()
        # Verificar si df está vacío para evitar FutureWarning
        if df.empty:
            df = new_row.copy()
        else:
            df = pd.concat([df, new_row], ignore_index=True)

        return df


    def _get_names_columns_direction_contact(self):
        """Get mapping of direction-related columns to DIAN codes.

        Uses _get_format_field_ref() for consistency and to leverage env.ref() internal caching.
        """
        result = {}
        field_dpto = self._get_format_field_ref('dpto')
        field_pais = self._get_format_field_ref('pais')

        if field_dpto:
            result[field_dpto.name] = dian_department_codes
        if field_pais:
            result[field_pais.name] = dian_countries_codes

        return result

    def _normalize_partner_street(self, names_columns_direction_contact, original_dataframe):
        for column in names_columns_direction_contact:
            # Es una buena práctica asegurarse de que las claves del diccionario de reemplazo
            # sean cadenas en minúsculas. Si 'key' no es siempre un string, str(key) lo convierte.
            replacement_dict = {str(key).lower(): value for key, value in names_columns_direction_contact[column].items()}
            
            if column in original_dataframe.columns:
                # Convertir la columna a tipo string ANTES de usar el accesor .str
                # Esto manejará números, booleanos, y valores NaN (convirtiéndolos a la cadena 'nan').
                original_dataframe[column] = original_dataframe[column].astype(str).str.lower().map(replacement_dict)
                
        return original_dataframe

    def _normalize_partner_identification(self, original_dataframe):
        """Normalize partner identification numbers and verification digits.

        For NIT document types, splits identification into number and verification digit,
        recalculates the DV if needed. Uses dynamic NIT code detection.

        Vectorized implementation:
        - String split via Series.str.partition (single C-level call vs N apply calls).
        - _check_dv is invoked once per UNIQUE NIT (typically O(100s)) instead of once per
          dataframe row (typically O(1000s–100Ks)). The DIAN module-11 calculation is the
          most expensive single piece of arithmetic in this method.
        """
        field_tdoc = self._get_format_field_ref('tdoc')
        field_nid = self._get_format_field_ref('nid')
        field_dv = self._get_format_field_ref('dv')

        if not field_tdoc or not field_nid:
            return original_dataframe

        field_tdoc_name = field_tdoc.name
        field_nid_name = field_nid.name
        field_dv_name = field_dv.name if field_dv else None

        if field_nid_name not in original_dataframe.columns:
            _logger.warning(
                "Column '%s' not found in dataframe. Available columns: %s",
                field_nid_name, list(original_dataframe.columns),
            )
            return original_dataframe

        if field_tdoc_name not in original_dataframe.columns:
            _logger.warning(
                "Column '%s' not found in dataframe. Available columns: %s",
                field_tdoc_name, list(original_dataframe.columns),
            )
            return original_dataframe

        nit_code = self._get_nit_document_code()
        nit_mask = original_dataframe[field_tdoc_name] == nit_code
        if not nit_mask.any():
            return original_dataframe

        filtered_indices = original_dataframe.index[nit_mask]
        nit_raw = original_dataframe.loc[filtered_indices, field_nid_name]

        # "Falsy" rows: original code's `if not nit: return [nit, None]`.
        # Upstream pipeline normalizes False/NaN to '' so the typical falsy is empty string.
        nit_str_raw = nit_raw.astype(str)
        falsy_mask = (
            nit_raw.isna()
            | (nit_str_raw == '')
            | (nit_str_raw == 'False')
            | (nit_str_raw == 'None')
        )

        # Vectorized partition: returns 3 cols (before, sep, after) — empty strings
        # when separator absent. Single C-level pass, no Python apply.
        parts = nit_str_raw.str.partition('-')
        has_dash = parts[1] == '-'

        # Initialize numero = full string, dv_actual = None.
        numero = nit_str_raw.copy()
        dv_actual = pd.Series([None] * len(nit_str_raw), index=nit_str_raw.index, dtype=object)

        # Case 1: has '-'  → numero = before, dv_actual = after.
        if has_dash.any():
            numero.loc[has_dash] = parts.loc[has_dash, 0]
            dv_actual.loc[has_dash] = parts.loc[has_dash, 2]

        # Case 2: no '-', len > 1 → numero = str[:-1], dv_actual = str[-1].
        no_dash_long = (~has_dash) & (nit_str_raw.str.len() > 1)
        if no_dash_long.any():
            numero.loc[no_dash_long] = nit_str_raw[no_dash_long].str[:-1]
            dv_actual.loc[no_dash_long] = nit_str_raw[no_dash_long].str[-1]

        # Case 3: no '-', len <= 1 → numero = full string (already set), dv_actual = None (already set).

        # Falsy rows: restore raw value and force dv None.
        if falsy_mask.any():
            numero.loc[falsy_mask] = nit_raw.loc[falsy_mask]
            dv_actual.loc[falsy_mask] = None

        # Compute _check_dv only on unique numero values. This is the dominant cost
        # of the original method when there are many rows but few distinct partners.
        if field_dv_name:
            valid_numero = numero[~falsy_mask].dropna()
            unique_numeros = pd.unique(valid_numero)
            dv_map = {}
            for n in unique_numeros:
                n_str = n if isinstance(n, str) else str(n)
                try:
                    dv_map[n_str] = _check_dv(n_str)
                except (ValueError, TypeError, AttributeError) as e:
                    _logger.debug("Could not calculate DV for %s: %s", n_str, e)
                    dv_map[n_str] = None  # sentinel: fall back to dv_actual

            # Final DV: dv_map[n] if present and non-None, else dv_actual.
            def _resolve(n, fallback):
                if n is None or (isinstance(n, float) and pd.isna(n)):
                    return None
                key = n if isinstance(n, str) else str(n)
                new_dv = dv_map.get(key)
                return new_dv if new_dv is not None else fallback

            final_dv = pd.Series(
                [_resolve(numero.iat[i], dv_actual.iat[i]) for i in range(len(numero))],
                index=numero.index, dtype=object,
            )
            if falsy_mask.any():
                final_dv.loc[falsy_mask] = None

            original_dataframe.loc[filtered_indices, field_dv_name] = final_dv.values

        original_dataframe.loc[filtered_indices, field_nid_name] = numero.values
        return original_dataframe

    # Account-type sets used by closing_balance asset_liability mode.
    # Module-level constants would be cleaner; kept inline to avoid touching
    # imports in a hot file. Values mirror Odoo 17 account.account.account_type.
    _DEBIT_NATURE_ACCOUNT_TYPES = frozenset({
        'asset_receivable', 'asset_cash', 'asset_current', 'asset_non_current',
        'asset_prepayments', 'asset_fixed', 'expense', 'expense_depreciation',
        'expense_direct_cost', 'off_balance',
    })
    _CREDIT_NATURE_ACCOUNT_TYPES = frozenset({
        'liability_payable', 'liability_credit_card', 'liability_current',
        'liability_non_current', 'equity', 'equity_unaffected', 'income', 'income_other',
    })

    def _select_fields_from_account_move_line(self, setting_line, df_account_move_lines):
        """Apply accumulation method to account move lines for a specific format field.

        Vectorized implementation. The previous version used df.apply(get_column_value, axis=1)
        which calls a Python closure once per row — fine for ~10K rows, catastrophic
        for ~100K+ (full year). Here we build per-account dictionaries once and use
        Series.map / boolean masks so the work happens at NumPy/pandas C-level.

        Métodos de acumulación soportados (semántica idéntica al método anterior):
        - 'debit', 'credit', 'balance', 'tax_base_amount': valor directo de la columna.
        - 'tax_amount': abs(balance) si la fila tiene tax_line_id; 0.0 en caso contrario.
        - 'closing_balance':
            * asset_liability: balance si account_type ∈ debit_nature; -balance si ∈ credit_nature;
              balance tal cual si el tipo es desconocido.
            * account_prefix: balance si display_name comienza con un prefijo de activo;
              -balance si comienza con uno de pasivo; balance tal cual en otros casos.
        """
        if df_account_move_lines.empty:
            return df_account_move_lines

        format_field_accumulated = self._format_field_by_accumulated(setting_line)
        field_name, account_operations = next(iter(format_field_accumulated.items()))

        valid_operations = {'credit', 'debit', 'balance', 'tax_base_amount', 'tax_amount', 'closing_balance'}

        # account_operations keys are tuples (account_id, account_display_name).
        # Flatten to two id-keyed dicts so we can drive everything via vectorized
        # Series.map() against the integer account_id extracted from the dataframe.
        op_by_id = {}
        display_name_by_id = {}
        for acc_key, op in account_operations.items():
            if op not in valid_operations:
                continue
            if isinstance(acc_key, (list, tuple)):
                acc_id, acc_display = acc_key[0], (acc_key[1] if len(acc_key) > 1 else '')
            else:
                acc_id, acc_display = acc_key, ''
            op_by_id[acc_id] = op
            display_name_by_id[acc_id] = acc_display if isinstance(acc_display, str) else str(acc_display)

        needs_account_type = any(op == 'closing_balance' for op in op_by_id.values())

        # Build closing-balance sign map (+1 / -1) per account id once.
        # Default sign is +1 (balance returned as-is) for non-closing-balance ops
        # and for closing_balance with unknown account type / unmatched prefix.
        sign_by_id = {}
        if needs_account_type:
            cb_account_ids = [acc_id for acc_id, op in op_by_id.items() if op == 'closing_balance']
            if self.closing_balance_method == 'asset_liability':
                accounts = self.env['account.account'].browse(cb_account_ids)
                acc_type_by_id = {acc.id: acc.account_type for acc in accounts}
                for acc_id in cb_account_ids:
                    acc_type = acc_type_by_id.get(acc_id)
                    if acc_type in self._CREDIT_NATURE_ACCOUNT_TYPES:
                        sign_by_id[acc_id] = -1
                    else:
                        # debit_nature OR unknown → balance as-is
                        sign_by_id[acc_id] = 1
            else:
                prefixes_asset = [p.strip() for p in (self.asset_account_prefixes or '1').split(',')]
                prefixes_liability = [p.strip() for p in (self.liability_account_prefixes or '2').split(',')]
                for acc_id in cb_account_ids:
                    code = display_name_by_id.get(acc_id, '')
                    if any(code.startswith(p) for p in prefixes_asset):
                        sign_by_id[acc_id] = 1
                    elif any(code.startswith(p) for p in prefixes_liability):
                        sign_by_id[acc_id] = -1
                    else:
                        sign_by_id[acc_id] = 1  # legacy: balance as-is

        # Extract integer account_id once. search_read returns (id, display_name);
        # _read_group rows in this module also pre-pack as a tuple. Both supported.
        acc_id_series = df_account_move_lines['account_id'].map(
            lambda x: x[0] if isinstance(x, (list, tuple)) else x
        )

        # Per-row operation. NaN for rows whose account is not in op_by_id (defensive).
        op_series = acc_id_series.map(op_by_id)

        # Result column initialized to 0.0 — covers invalid/missing operations and
        # tax_amount rows without tax_line_id.
        result = pd.Series(0.0, index=df_account_move_lines.index, dtype='float64')

        # Direct column copy for the four "value-pass-through" operations.
        for op_name in ('debit', 'credit', 'balance', 'tax_base_amount'):
            mask = (op_series == op_name)
            if mask.any() and op_name in df_account_move_lines.columns:
                result.loc[mask] = pd.to_numeric(
                    df_account_move_lines.loc[mask, op_name], errors='coerce'
                ).fillna(0.0).astype('float64')

        # tax_amount: abs(balance) only on rows with tax_line_id truthy.
        # tax_line_id from search_read is False or (id, name); from _read_group it's missing → NaN.
        # We treat tuple/list as truthy (mirrors `if tax_line_id:` semantics on real data).
        mask_tax_op = (op_series == 'tax_amount')
        if mask_tax_op.any() and 'tax_line_id' in df_account_move_lines.columns:
            tax_line = df_account_move_lines['tax_line_id']
            # Vectorized truthiness via list-comprehension — single Python pass, much faster
            # than apply(axis=1) over the whole row.
            tax_line_truthy = pd.Series(
                [isinstance(v, (list, tuple)) and len(v) > 0 for v in tax_line],
                index=tax_line.index,
            )
            mask_tax = mask_tax_op & tax_line_truthy
            if mask_tax.any():
                result.loc[mask_tax] = pd.to_numeric(
                    df_account_move_lines.loc[mask_tax, 'balance'], errors='coerce'
                ).fillna(0.0).abs().astype('float64')

        # closing_balance: balance * sign_by_id[account_id]; default sign 1.
        if needs_account_type:
            mask_cb = (op_series == 'closing_balance')
            if mask_cb.any() and 'balance' in df_account_move_lines.columns:
                sign_series = acc_id_series.map(sign_by_id).fillna(1).astype('int64')
                balance_series = pd.to_numeric(
                    df_account_move_lines.loc[mask_cb, 'balance'], errors='coerce'
                ).fillna(0.0).astype('float64')
                result.loc[mask_cb] = balance_series * sign_series.loc[mask_cb]

        df_account_move_lines[field_name] = result
        return df_account_move_lines

    def _get_field_or_concepts_and_field(self):
        vals = {}
        for setting_line in self.format_setting_line_ids:
            if self.format_id.apply_concepts:
                for field_account in setting_line.format_field_id.field_account_ids:
                    if field_account.concept_id.code not in vals:
                        vals[field_account.concept_id.code] = [field_account.format_field_id.name]
                    else:
                        vals[field_account.concept_id.code].append(field_account.format_field_id.name)
            else:
                for field_account in setting_line.format_field_id.field_account_ids:
                        vals[setting_line.format_field_id.name] = setting_line.format_field_id.name
        return vals


    def _process_smaller_amounts_for_fields(self, original_dataframe, fields, threshold, base_mask=None):
        """Process smaller amounts for a list of fields.

        Args:
            original_dataframe: DataFrame to process
            fields: List of field names to check
            threshold: Amount threshold for smaller amounts
            base_mask: Optional base mask to combine with field mask

        Returns:
            tuple: (new_row dict with summed amounts, bool indicating if row should be added)
        """
        new_row = {}
        add_new_row = False

        for field in fields:
            if field not in original_dataframe.columns:
                continue

            # Create mask for values within threshold
            field_mask = (
                (original_dataframe[field] <= threshold) &
                (original_dataframe[field] >= -threshold)
            )

            # Combine with base mask if provided
            if base_mask is not None:
                field_mask = field_mask & base_mask

            # Sum smaller amounts
            smaller_amounts = original_dataframe.loc[field_mask, field].sum()

            if smaller_amounts != 0:
                # Zero out smaller values in original
                original_dataframe.loc[field_mask, field] = 0
                new_row[field] = smaller_amounts
                add_new_row = True

        return new_row, add_new_row

    def process_smaller_amount_dataframe(self, original_dataframe):
        """Process smaller amounts aggregation for the dataframe.

        Aggregates values below the threshold into a single "smaller amounts" row
        per concept (if applicable) or as a single row for the entire dataframe.
        """
        if not self.format_id.applying_smaller_amounts:
            return original_dataframe

        concept_or_field = self._get_field_or_concepts_and_field()
        threshold = self.format_id.smaller_ammounts

        if self.format_id.apply_concepts:
            # Cache concept field name outside the loop
            concept_field = self._get_field_concept()
            concept_field_name = concept_field.name if concept_field else None

            for concept, fields in concept_or_field.items():
                base_row = self._get_fields_fill_smaller_amount()
                if concept_field_name:
                    base_row[concept_field_name] = concept

                # Create concept mask
                concept_mask = (
                    original_dataframe[concept_field_name] == concept
                    if concept_field_name and concept_field_name in original_dataframe.columns
                    else None
                )

                field_amounts, should_add = self._process_smaller_amounts_for_fields(
                    original_dataframe, fields, threshold, concept_mask
                )

                if should_add:
                    base_row.update(field_amounts)
                    original_dataframe = self._generate_row_by_smaller_amount(base_row, original_dataframe)
        else:
            base_row = self._get_fields_fill_smaller_amount()
            fields = list(concept_or_field.keys())

            field_amounts, should_add = self._process_smaller_amounts_for_fields(
                original_dataframe, fields, threshold
            )

            if should_add:
                base_row.update(field_amounts)
                original_dataframe = self._generate_row_by_smaller_amount(base_row, original_dataframe)

        return original_dataframe

    def _group_dataframe(self, setting_line, columns_ordered, unique_keys_by_format, fields_contact, df_account_move_lines):
        operations = {column: 'first' if column not in self._get_fields_format_id(setting_line) else 'sum'
                    for column in columns_ordered}

        df_account_move_lines_copy = df_account_move_lines.copy(deep=True)
        filtered_grouped = df_account_move_lines_copy.groupby(unique_keys_by_format)

        result = filtered_grouped.agg(operations).round(0)
        if fields_contact:
            return result.rename(columns=self._get_fields_odoo_and_format(fields_contact))
        return result

    def generate_and_download_report(self):
        """Generate and download exogenous information report.

        This is the main orchestrator method that coordinates the entire report generation process.
        
        **Flujo de Generación (Formato 1001 como ejemplo):**
        
        1. **Configuración y Validación:**
           - Valida la configuración del formato
           - Obtiene los campos configurados (ej: pago, pnded, ided, retp, etc.)
           
        2. **Procesamiento por Campo (Loop setting_line):**
           Para cada campo del formato (pago, pnded, ided...):
           a. Obtiene las configuraciones de cuentas (field_account_ids)
           b. Por cada configuración (concepto + cuentas):
              - Consulta account.move.line filtrando por las cuentas configuradas
              - Aplica el método de acumulación configurado (debit/credit/balance/etc.)
              - Extrae partner_ids únicos
           c. Obtiene información de partners (NIT, razón social, dirección, etc.)
           d. Normaliza y fusiona datos contables con datos de partners
           e. Aplica el cálculo según _selection_accumulated_by configurado
           f. Renombra columnas según nombres de campos del formato
           g. Acumula en el dataframe principal (original_dataframe)
           
        3. **Consolidación y Agrupación:**
           - Agrupa por llaves únicas (tdoc, nid, concepto)
           - Suma campos monetarios
           - Mantiene campos de contacto (first)
           
        4. **Post-Procesamiento:**
           - Normaliza direcciones (códigos DIAN departamentos/países)
           - Calcula dígito de verificación para NITs
           - Procesa cuantías menores si aplica
           - Agrega línea de "Movimientos sin terceros"
           - Filtra filas con todos los valores en 0
           
        5. **Generación del Archivo:**
           - Crea archivo Excel con openpyxl
           - Retorna archivo codificado en base64
        
        **Ejemplo Formato 1001:**
        Si tienes configurado:
        - Campo "pago" → Concepto 5002 → Cuentas 51xxxx → Método: debit
        - Campo "retp" → Concepto 5002 → Cuentas 2365xx → Método: credit
        
        El método:
        1. En la primera iteración procesa "pago", extrae débitos de 51xxxx
        2. En la segunda iteración procesa "retp", extrae créditos de 2365xx
        3. Ambos comparten el mismo partner y concepto, se agrupan en una fila
        4. Resultado: Una fila por partner con pago=XXXX, retp=YYYY, concepto=5002

        Raises:
            UserError: If configuration is incomplete or invalid
            ValidationError: If data validation fails
        """
        # Validate configuration
        self._validate_report_configuration()

        # Validate date ranges (only when generating report)
        self._check_dates()

        # Retrieve format fields
        format_fields = self.env['l10n_co.exogenous_format_field'].search(
            [('format_ids', 'in', self.format_id.id)], order="sequence asc")

        if not format_fields:
            raise UserError(_("No se han configurado campos para el formato: %s", self.format_id.code))

        # Filter fields based on source
        fields_contact = format_fields.filtered(lambda ff: ff.source == 'contact')

        # Get fields to clear for contact and company
        fields_to_clear_contact = self._get_fields_to_clear_contact(fields_contact)
        fields_to_clear_company = self._get_fields_to_clear_company(fields_contact)

        # Get unique keys for format
        unique_keys_by_format = format_fields.filtered(lambda ff: ff.is_unique_key).mapped(
            'field_odoo_id').mapped('name')

        unique_keys_by_format_field = format_fields.filtered(lambda ff: ff.is_unique_key).mapped('name')

        if self.format_id.apply_concepts:
            unique_keys_by_format = unique_keys_by_format + ['account_id']

        wb = Workbook()
        ws = wb.active
        ws = _column_name_field(format_fields.mapped('name'), ws)

        # Create original dataframe
        original_dataframe = self._create_original_dataframe(format_fields)
        columnas_originales = original_dataframe.columns
        original_dataframe_without_partner = original_dataframe.copy(deep=True)

        # Cache frequently used values to avoid repeated ORM calls
        format_field_names = self.format_setting_line_ids.mapped('format_field_id').mapped('name')
        field_concept = self._get_format_field_ref('cpt')
        field_raz = self._get_format_field_ref('raz')

        names_columns_direction_contact = self._get_names_columns_direction_contact()
        concepts = self._get_accounts_by_format()

        # Cache document types outside the loop (called once instead of N times)
        df_type_documents = pd.DataFrame(self._get_type_documents_by_format())

        # ============================================================================
        # Phase 1: Collect aggregated AML data per setting_line. No partner queries
        # yet — we accumulate the union of partner_ids so that Phase 2 can fetch
        # res.partner data in a single batched read.
        # ============================================================================
        setting_payload = []  # list of (setting_line, partner_ids set, amls list)
        all_partner_ids = set()
        for setting_line in self.format_setting_line_ids:
            field_accounts = self._get_field_account(setting_line)
            amls = []
            pids = set()
            for field_account in field_accounts:
                data = self._get_information_by_account_move_line(field_account)
                pids |= set(data[0])
                amls += data[1]
            setting_payload.append((setting_line, pids, amls))
            all_partner_ids |= pids

        # ============================================================================
        # Phase 2: Single batched res.partner fetch + normalization. The previous
        # implementation re-fetched and re-normalized the same partners once per
        # setting_line; for a 1001 with 5 monetary fields and 5K partners that was
        # ~5 redundant search_reads + 5 normalize passes. Now we do one of each
        # and reuse df_partners_all in every Phase 3 merge.
        # ============================================================================
        df_partners_all = pd.DataFrame()
        partners_fetch_failed = False
        if all_partner_ids:
            partners, other_info_contact = self._get_information_partner(
                all_partner_ids, fields_contact,
            )
            if isinstance(partners, dict) and partners.get('tag', False):
                _logger.warning(
                    "Unexpected dict return from _get_information_partner: %s", partners,
                )
                partners_fetch_failed = True
            else:
                df_partners_all = pd.DataFrame(partners).fillna('').replace({False: ''})
                df_other_info = pd.DataFrame([other_info_contact])
                df_partners_all = self._normalize_partner_dataframe(
                    self._get_field_name_second_field_many2one(fields_contact),
                    df_partners_all, df_type_documents, df_other_info,
                    fields_to_clear_contact, fields_to_clear_company,
                )

        # ============================================================================
        # Phase 3: Per setting_line — split, merge against the cached partner frame,
        # apply accumulation method, concat to global dataframe.
        # ============================================================================
        get_information = []
        fields_odoo_and_format = self._get_fields_odoo_and_format(fields_contact)
        for setting_line, pids, amls in setting_payload:
            if not amls or not pids:
                get_information.append(False)
                continue
            if partners_fetch_failed:
                # Preserve original behavior: skip this setting_line if the partner
                # fetch returned an unexpected shape. With caching, this affects all
                # setting_lines uniformly — same as the original `continue` case.
                get_information.append(False)
                continue

            get_information.append(True)

            df_account_move_lines = pd.DataFrame(amls)

            has_partner_mask = (
                df_account_move_lines['partner_id'].notna()
                & (df_account_move_lines['partner_id'] != '')
                & (df_account_move_lines['partner_id'].astype(bool))
            )
            df_account_move_lines_without_partner = df_account_move_lines[~has_partner_mask]
            df_account_move_lines = df_account_move_lines[has_partner_mask]

            df_account_move_lines = self._normalize_and_merge_account_move_lines(
                df_account_move_lines, df_partners_all,
            )

            df_account_move_lines = self._select_fields_from_account_move_line(
                setting_line, df_account_move_lines,
            )
            df_account_move_lines_without_partner = self._select_fields_from_account_move_line(
                setting_line, df_account_move_lines_without_partner,
            )

            df_account_move_lines['account_id'] = df_account_move_lines['account_id'].apply(
                lambda x: concepts.get(x[0], x[0]),
            )
            df_account_move_lines_without_partner['account_id'] = df_account_move_lines_without_partner['account_id'].apply(
                lambda x: concepts.get(x[0], x[0]),
            )

            result = df_account_move_lines.rename(columns=fields_odoo_and_format)

            if not result.empty:
                if original_dataframe.empty:
                    original_dataframe = result.copy()
                else:
                    original_dataframe = pd.concat(
                        [original_dataframe, result], ignore_index=True,
                    )

            if not df_account_move_lines_without_partner.empty:
                if original_dataframe_without_partner.empty:
                    original_dataframe_without_partner = df_account_move_lines_without_partner.copy()
                else:
                    original_dataframe_without_partner = pd.concat(
                        [original_dataframe_without_partner, df_account_move_lines_without_partner],
                        ignore_index=True,
                    )

        if not any(get_information):
            raise UserError(_("No se encontraron datos que coincidan con los criterios especificados. "
                            "Por favor verifique el rango de fechas, diarios excluidos y contactos excluidos."))

        original_dataframe = original_dataframe.reindex(columns=columnas_originales)
        #original_dataframe_without_partner = original_dataframe_without_partner.reindex(columns=columnas_originales)

        # Log columns that have all NaN values (might indicate missing configuration)
        nan_columns = [col for col in original_dataframe.columns if original_dataframe[col].isna().all()]
        if nan_columns:
            _logger.warning(
                "The following columns have all NaN values (might need configuration): %s",
                nan_columns
            )

        original_dataframe = self._normalize_partner_street(names_columns_direction_contact, original_dataframe)
        original_dataframe = self._normalize_partner_identification(original_dataframe)

        # Only include columns that exist in the dataframe
        existing_columns = [col for col in columnas_originales if col in original_dataframe.columns]
        operations = {column: 'first' if column not in format_field_names else 'sum'
            for column in existing_columns}

        filtered_grouped = original_dataframe.groupby(unique_keys_by_format_field)
        original_dataframe = filtered_grouped.agg(operations).round(0)
        original_dataframe = self.process_smaller_amount_dataframe(original_dataframe)


        # Aggregate the "Movimientos sin terceros" rows. When no setting_line
        # contributed no-partner AML rows, original_dataframe_without_partner
        # remains in its initial state (created via _create_original_dataframe,
        # which uses format-field names as columns and does NOT include
        # 'account_id'). In that case we must skip the groupby/sum entirely.
        no_partner_empty = (
            original_dataframe_without_partner.empty
            or 'account_id' not in original_dataframe_without_partner.columns
        )

        if self.format_id.apply_concepts:
            if no_partner_empty:
                # Replace with an empty frame so the downstream dataframe_to_rows
                # loop is a no-op (no synthetic "Movimientos sin terceros" row).
                original_dataframe_without_partner = pd.DataFrame()
            else:
                existing_fields = [field for field in format_field_names
                                 if field in original_dataframe_without_partner.columns]
                operations_2 = {field: 'sum' for field in existing_fields}
                operations_2['account_id'] = 'first'
                filtered_grouped2 = original_dataframe_without_partner.groupby(['account_id'])
                original_dataframe_without_partner = filtered_grouped2.agg(operations_2).round(0)
        else:
            # Only sum fields that exist in the dataframe
            existing_fields = [field for field in format_field_names
                             if field in original_dataframe_without_partner.columns]
            if existing_fields and not original_dataframe_without_partner.empty:
                sum_row = original_dataframe_without_partner[existing_fields].sum()
                original_dataframe_without_partner = pd.DataFrame([sum_row])
            else:
                # No no-partner rows → no aggregated row needed.
                original_dataframe_without_partner = pd.DataFrame()
        
        for row_data in dataframe_to_rows(original_dataframe_without_partner, index=False, header=False):
            new_row = self._get_fields_fill_smaller_amount()

            # Fill new_row dynamically using cached field names
            if self.format_id.apply_concepts and field_concept:
                new_row.update({field_concept.name: row_data[original_dataframe_without_partner.columns.get_loc('account_id')]})

            # Only process columns that exist in the dataframe
            for col_name in format_field_names:
                if col_name in original_dataframe_without_partner.columns:
                    new_row[col_name] = row_data[original_dataframe_without_partner.columns.get_loc(col_name)]

            if field_raz:
                new_row[field_raz.name] = self.no_partner_name or 'Movimientos sin terceros'
            original_dataframe = self._generate_row_by_smaller_amount(new_row, original_dataframe)

        # Only check columns that exist in the dataframe
        existing_format_fields = [col for col in format_field_names if col in original_dataframe.columns]
        if existing_format_fields:
            condition = reduce(operator.or_, [(original_dataframe[col] != 0) for col in existing_format_fields])
        else:
            condition = pd.Series([False] * len(original_dataframe))

        # Filtrar el DataFrame
        original_dataframe = original_dataframe[condition]

        # Clean up negative values and NaN before writing to Excel
        # DIAN doesn't allow negative values in exogenous reports
        original_dataframe = self._clean_dataframe_for_export(original_dataframe, format_field_names)

        # Get column indices for ALL numeric fields to apply number formatting
        # This includes format fields AND partner fields (DV, phone, etc.)
        numeric_col_indices = []
        for col_name in original_dataframe.columns:
            # Check if column contains numeric data (int or float dtype)
            if pd.api.types.is_numeric_dtype(original_dataframe[col_name].dtype):
                numeric_col_indices.append(original_dataframe.columns.get_loc(col_name) + 1)  # +1 for Excel 1-based indexing

        # Write data rows
        start_row = ws.max_row + 1  # Track starting row for formatting
        for row_data in dataframe_to_rows(original_dataframe, index=False, header=False):
            ws.append(row_data)

        # Apply number format to ALL numeric columns: integer without decimals or separators
        # DIAN patrón técnico {1,18}: números enteros sin decimales ni signos de puntuación
        end_row = ws.max_row
        for row_idx in range(start_row, end_row + 1):
            for col_idx in numeric_col_indices:
                cell = ws.cell(row=row_idx, column=col_idx)
                # Format as integer without thousand separators or decimals
                cell.number_format = '0'

        output = io.BytesIO()
        wb.save(output)
        file_name = f"exogena_{self.format_id.code}_{datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)}"
        self.binary_file = base64.b64encode(output.getvalue())
        self.binary_file_name = f"{file_name}.xlsx"


