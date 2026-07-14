-- يُولَّد فعلياً على الخادم بكلمة مرور قوية عبر infra/deploy/oracle.sh — هذا نموذج
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medify_app') THEN
        CREATE ROLE medify_app LOGIN PASSWORD 'REPLACED_BY_ORACLE_SH';
    END IF;
END $$;
