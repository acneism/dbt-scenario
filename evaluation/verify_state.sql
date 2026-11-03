{% macro verify_state(expected_schema) %}
  {% set expected = api.Relation.create(database=target.database, schema=expected_schema, identifier='expected') %}
  {% set actual = ref('fct_orders') %}
  {% set result = namespace(reason=none) %}
  {% set schema = run_query(audit_helper.compare_relation_columns(expected, actual)) %}
  {% for row in schema.rows %}
    {% if not row['in_both'] or not row['has_data_type_match'] %}
      {% set result.reason = 'SCHEMA_MISMATCH' %}
    {% endif %}
  {% endfor %}
  {% if result.reason is none %}
    {% set counts = run_query(audit_helper_ext.compare_row_counts(expected, actual)) %}
    {% if counts.rows[0]['total_records'] != counts.rows[1]['total_records'] %}
      {% set result.reason = 'ROW_COUNT_MISMATCH' %}
    {% endif %}
  {% endif %}
  {% if result.reason is none %}
    {% set compared = run_query(audit_helper_ext.compare_relations(expected, actual, primary_key='order_id')) %}
    {% for row in compared.rows %}
      {% if not row['in_a'] or not row['in_b'] %}
        {% set result.reason = 'ROWS_MISMATCH' %}
      {% endif %}
    {% endfor %}
  {% endif %}
  {% do log('EVALUATION_GATE=' ~ tojson({'status': 'FAIL' if result.reason else 'PASS', 'reason_code': result.reason}), info=true) %}
  {% if result.reason %}
    {% do exceptions.raise_compiler_error('EVALUATION_ASSERTION_FAILED') %}
  {% endif %}
{% endmacro %}
