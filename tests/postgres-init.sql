CREATE SCHEMA core;

CREATE TABLE core.sensor_mst (
    id int4 PRIMARY KEY,
    line_code text NOT NULL,
    equip_name text NOT NULL,
    sensor_code text NOT NULL,
    equip_id int4 NOT NULL
);

INSERT INTO core.sensor_mst (id, line_code, equip_name, sensor_code, equip_id)
VALUES
    (10, 'LO054', 'MC02', 'TEMP_BT', 20),
    (11, 'LO054', 'MC02', 'STATUS', 20),
    (211, 'LO054', 'MC02', 'Temp_ST01_PL01', 20),
    (212, 'LO054', 'MC02', 'Temp_ST01_PL02', 20);

CREATE VIEW core.v_topic_mapping AS
SELECT line_code, equip_name, sensor_code, id AS sensor_id, equip_id
FROM core.sensor_mst;

CREATE TABLE core.sensor_status (
    id int8 GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id int4 NOT NULL,
    conn_status varchar(50) DEFAULT 'off' NOT NULL,
    last_seen timestamptz NULL,
    health_score float8 NULL,
    error_msg text NULL,
    update_time timestamptz DEFAULT (now() AT TIME ZONE 'UTC') NOT NULL,
    CONSTRAINT sensor_status_sensor_id_fkey
        FOREIGN KEY (sensor_id) REFERENCES core.sensor_mst(id) ON DELETE CASCADE
);

CREATE INDEX idx_sensor_status_sensor_update
    ON core.sensor_status (sensor_id, update_time DESC);
