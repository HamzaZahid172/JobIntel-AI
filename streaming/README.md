# Streaming layer

The Docker `data` profile starts Redpanda (Kafka-compatible). Planned event contracts:
- `job.discovered`
- `job.normalized`
- `application.created`
- `application.status_changed`

The core app does not require Redpanda, so local development remains lightweight and free.
