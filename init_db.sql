-- ET4242 IoT Practical 05: MariaDB Initialization Script
CREATE DATABASE IF NOT EXISTS iot_lab CHARACTER SET utf8mb4;
USE iot_lab;

-- Drop existing tables if restarting
DROP TABLE IF EXISTS sensor_readings;
DROP TABLE IF EXISTS devices;

CREATE TABLE devices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_name VARCHAR(32) NOT NULL UNIQUE,
    location VARCHAR(100),
    sensor_type VARCHAR(30),
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE sensor_readings (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    device_id INT NOT NULL,
    temperature_c DECIMAL(5,2) NOT NULL,
    humidity_percent DECIMAL(5,2) NOT NULL,
    recorded_at DATETIME(3) NOT NULL, -- UTC, set by the device
    UNIQUE KEY uq_device_time (device_id, recorded_at),
    CONSTRAINT fk_reading_device FOREIGN KEY (device_id) REFERENCES devices(id),
    CONSTRAINT chk_temp CHECK (temperature_c BETWEEN -40 AND 80),
    CONSTRAINT chk_hum CHECK (humidity_percent BETWEEN 0 AND 100)
) ENGINE=InnoDB;

-- Create users with matching credentials configured in db.ini
CREATE OR REPLACE USER 'iot_writer'@'localhost' IDENTIFIED BY 'WriterSecurePass_Et4242_2026!';
CREATE OR REPLACE USER 'iot_reader'@'localhost' IDENTIFIED BY 'ReaderSecurePass_Et4242_2026!';

GRANT SELECT ON iot_lab.devices TO 'iot_writer'@'localhost';
GRANT SELECT, INSERT, UPDATE ON iot_lab.sensor_readings TO 'iot_writer'@'localhost';
GRANT SELECT ON iot_lab.* TO 'iot_reader'@'localhost';

-- Benchmark table for Part 4
CREATE TABLE IF NOT EXISTS iot_lab.bench_readings LIKE iot_lab.sensor_readings;
GRANT SELECT, INSERT, UPDATE, DELETE, ALTER, INDEX ON iot_lab.bench_readings TO 'iot_writer'@'localhost';

FLUSH PRIVILEGES;

-- Seed initial device
INSERT INTO devices (device_name, location, sensor_type)
VALUES ('pi-01', 'Laboratory', 'DHT11 or simulated');

