-- Script to clean up orphaned foreign key references
-- Run this if you encounter foreign key constraint violations

-- Check for orphaned records in the relation table
SELECT format_id, COUNT(*) as count
FROM l10n_co_exogenous_format_field_rel
WHERE format_id NOT IN (SELECT id FROM l10n_co_exogenous_format)
GROUP BY format_id;

-- Delete orphaned records (uncomment to execute)
DELETE FROM l10n_co_exogenous_format_field_rel
WHERE format_id NOT IN (SELECT id FROM l10n_co_exogenous_format);

-- Verify no orphaned records remain
SELECT COUNT(*) as orphaned_count
FROM l10n_co_exogenous_format_field_rel
WHERE format_id NOT IN (SELECT id FROM l10n_co_exogenous_format);