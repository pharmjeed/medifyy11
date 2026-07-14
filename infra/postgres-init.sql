-- دور التطبيق الخاضع لـ RLS (D-19) — كلمة المرور تُستبدل في الإنتاج عبر oracle.sh
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medify_app') THEN
        CREATE ROLE medify_app LOGIN PASSWORD 'medify_app_dev';
    END IF;
END $$;
