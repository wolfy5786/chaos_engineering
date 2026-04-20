-- Baseline migration for dummy_test auth.
-- Signup/login use Supabase Auth (GoTrue): identities and hashed passwords live in auth.users.
-- No public application tables are required for POST /signup and POST /login in services/auth.
SELECT 1;
