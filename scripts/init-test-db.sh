set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=test_password="$DSC_TEST_PASSWORD" <<'SQL'
CREATE ROLE dbt_scenario LOGIN PASSWORD :'test_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT, CREATE ON DATABASE dbt_scenario_test TO dbt_scenario;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
