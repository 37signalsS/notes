# Метрики безопасности Docker и SLO

**Актуально для:** Docker Engine 29.x, Trivy ≥ 0.70.1, Cosign v3.1.3, docker-bench-security (CIS Docker Benchmark v1.6.0).

Общие DevSecOps-метрики (coverage, MTTR, MTTT), стек мониторинга (Prometheus/Loki/Alertmanager), Grafana-дашборды и security-alerting — SSoT в [devsecops_monitoring.md](../../CI-CD/DevSecOps/devsecops_monitoring.md). Данный файл — Docker-специфичные метрики и security SLO/SLA: CIS score, drift rate, % signed, % scanned, % non-root, привилегированные контейнеры, EOL-образы.

## Определения

**Security metric (Docker)** — количественная мера состояния безопасности Docker-инфраструктуры, собираемая регулярно и сопоставляемая с целью (SLO). Источники: `docker inspect`, `trivy image`, `cosign verify`, `docker-bench-security`, `docker events`.

**SLI / SLO** — индикатор уровня обслуживания (измеряемая величина) и целевой уровень обслуживания (допустимое значение). Для Docker security: SLO определяет, насколько быстро и полно устраняются security-дефекты в образах и конфигурации демона.

**MTTR (Mean Time To Repair)** — среднее время от обнаружения security-дефекта до его устранения. Для Critical CVE — ключевой SLO.

**Drift rate** — доля running-контейнеров, фактическая конфигурация которых расходится с задекларированной (образ по digest, флаги безопасности, лимиты). Возникает при ручных изменениях (`docker exec`, `docker update`) и рассинхронизации Compose/CI.

**CIS score** — доля пройденных проверок CIS Docker Benchmark v1.6.0 через `docker-bench-security`. SSoT — [docker_bench_cis.md](./docker_bench_cis.md).

**Image freshness** — актуальность образа относительно upstream security-патчей. EOL-образ накапливает непропатченные CVE. SSoT — [image_freshness_policy.md](./image_freshness_policy.md).

## Предварительные требования

- **Docker Engine 29.x** — `docker inspect`, `docker events`, `docker stats`, `docker system df`.
- **Trivy ≥ 0.70.1** (≥ 0.74.x) — сканирование образов на CVE и EOL ОС. Критично из-за CVE-2026-33634 (компрометация образов сканера). SSoT — [vulnerability_scanning.md](./vulnerability_scanning.md).
- **Cosign v3.1.3** — проверка подписи образов. SSoT — [image_signature_and_verification.md](./image_signature_and_verification.md).
- **docker-bench-security** — образ на основе CIS Docker Benchmark v1.6.0. SSoT — [docker_bench_cis.md](./docker_bench_cis.md).
- **curl, jq, openssl** — парсинг JSON, вызовы API, проверка сертификатов.
- **Prometheus textfile collector** (опционально) — экспорт Docker-метрик в стек Prometheus/Grafana.
- **Node Exporter** (опционально) — метрики хоста (диск, память, сеть) для корреляции с Docker-метриками.

## Базовые концепции

### Категории Docker-security метрик

| Категория | Метрики | Источник |
| :--- | :--- | :--- |
| **Supply chain** | % просканированных, % подписанных, % pinned by digest, % non-root, число EOL-образов, возраст образа | `trivy image`, `cosign verify`, `docker inspect`, `docker images` |
| **Hardening** | CIS score, % контейнеров с `--read-only`, % с `--cap-drop=ALL`, число привилегированных контейнеров | `docker-bench-security`, `docker inspect` |
| **Runtime / drift** | drift rate, число `docker exec` в production, число pull из недоверенных реестров, OOM-события | `docker events`, `docker inspect`, `docker stats` |
| **Инциденты** | MTTR по severity, число инцидентов за период, число повторных (recurring) инцидентов | incident log, SIEM |

### Формулы

```
% scanned     = images_with_scan_result / total_images × 100
% signed      = images_with_valid_signature / total_images × 100
% pinned      = images_pinned_by_digest / total_images × 100
% non-root    = containers_with_nonempty_Config.User / total_containers × 100
drift rate    = containers_with_config_mismatch / total_containers × 100
MTTR(sev)     = mean(time_resolved − time_detected) для инцидентов severity=sev
CIS score     = passed_checks / total_checks × 100
EOL count     = images_with_eol_os / total_images × 100
```

### Почему Docker-метрики отдельно от общих DevSecOps

[devsecops_monitoring.md](../../CI-CD/DevSecOps/devsecops_monitoring.md) покрывает общие метрики (test coverage, MTTR, MTTT) и инфраструктуру сбора (Prometheus, Loki, Alertmanager, Falco). Docker-специфичные метрики требуют других источников данных:

| Источник | Что даёт |
| :--- | :--- |
| `docker inspect` | User, ReadonlyRootfs, CapDrop, Privileged, лимиты, digest образа |
| `trivy image` | CVE, EOL ОС (см. [image_freshness_policy.md](./image_freshness_policy.md)) |
| `cosign verify` | Наличие и валидность подписи (см. [image_signature_and_verification.md](./image_signature_and_verification.md)) |
| `docker-bench-security` | CIS score хоста и демона |
| `docker events` | exec_start, create, pull — операционный аудит |
| `docker stats` / `/containers/<id>/stats` | CPU, память, сеть, троттлинг, OOM (детали — в [docker_native_metrics.md](../Docker_metrics/docker_native_metrics.md)) |
| `cAdvisor` | Per-container метрики CPU/RAM/Network/Disk/PSI (детали — в [docker_native_metrics.md](../Docker_metrics/docker_native_metrics.md)) |

## Практические сценарии

### Сценарий 1: метрики образов из CI/CD

```bash
# 1. Сканирование (fail на CRITICAL и EOL)
trivy image --exit-code 1 --exit-on-eol 1 --severity CRITICAL my-app:v1
# → 0 vulnerabilities (или ERROR Detected EOL OS / exit code 1)

# 2. Проверка подписи
cosign verify --key cosign.pub my-registry.com/my-app:v1
# → Verification OK

# 3. Проверка non-root
docker inspect --format '{{.Config.User}}' my-app:v1
# → "10001:10001" (пустая строка = root — дефект)

# 4. Проверка digest pinning в Dockerfile
grep -E '^FROM .*@sha256:' Dockerfile
# → FROM my-registry.com/base@sha256:abc123...

# 5. Проверка EOL-ОС
trivy image --exit-on-eol 1 my-app:v1
# → ERROR Detected EOL OS: alpine 3.20.9
```

**Валидация:** Все 5 проверок возвращают `0` для дефектов (или exit code 0 для `cosign verify`).

### Сценарий 2: CIS score как метрика

```bash
# Запуск bench в JSON
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -v /etc:/etc:ro -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /usr/lib/systemd:/usr/lib/systemd:ro \
  -v /usr/bin/containerd:/usr/bin/containerd:ro \
  -v /usr/bin/runc:/usr/bin/runc:ro \
  --label docker_bench_security \
  docker/docker-bench-security -l json -o /tmp/bench.json

# Агрегация score
jq '[.tests[]?.results[]? | select(.result == "PASS")] | length' /tmp/bench.json
# → 187 (PASS из ~263 проверок)

# Итоговый score
jq -r '"Score: \(.score * 100 / .total_checks | floor)%"' /tmp/bench.json
# → Score: 71%
```

**Валидация:** JSON содержит массив `tests`; `score` вычисляется как доля Pass. Цель: ≥ 90% (с учётом обоснованных исключений).

### Сценарий 3: drift detection

Drift = расхождение running-контейнера с задекларированной конфигурацией:

```bash
# Digest образа running-контейнера vs актуальный в реестре
docker inspect --format '{{index .Image}}' my-app
docker images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}}' | grep my-app

# Флаги безопасности running-контейнера
docker inspect --format '{{json .HostConfig.SecurityOpt}} {{json .HostConfig.ReadonlyRootfs}} {{json .HostConfig.Privileged}}' my-app
# → ["no-new-privileges"] true false

# Обнаружение exec в production
docker events --since 24h --format '{{json .}}' | jq -r 'select(.Action=="exec_start") | "\(.Time) \(.Actor.Attributes.name)"'
```

Drift фиксируется, когда `docker update`/`docker exec` меняет конфигурацию вне CI. Метрика `drift_rate` собирается периодическим скриптом по всем контейнерам.

### Сценарий 4: экспортёр метрик для Prometheus

Минимальный экспортёр (Prometheus text format) — собирает Docker-security метрики:

```bash
#!/bin/sh
# /usr/local/bin/docker-security-metrics.sh
OUT=/var/lib/node_exporter/textfile_collector/docker_security.prom
{
  echo '# HELP docker_container_privileged Number of privileged containers'
  echo '# TYPE docker_container_privileged gauge'
  PRIV=$(docker ps -q | xargs -r docker inspect --format '{{.HostConfig.Privileged}}' | grep -c true || true)
  echo "docker_container_privileged $PRIV"

  echo '# HELP docker_container_root Number of containers running as root'
  echo '# TYPE docker_container_root gauge'
  ROOT=$(docker ps -q | xargs -r docker inspect --format '{{.Config.User}}' | grep -c '^$' || true)
  echo "docker_container_root $ROOT"

  echo '# HELP docker_container_readonly Number of containers with read-only rootfs'
  echo '# TYPE docker_container_readonly gauge'
  RO=$(docker ps -q | xargs -r docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' | grep -c true || true)
  echo "docker_container_readonly $RO"

  echo '# HELP docker_image_eol Number of EOL images in use'
  echo '# TYPE docker_image_eol gauge'
  EOL=$(docker images --format '{{.Repository}}:{{.Tag}}' | while read img; do
    trivy image --exit-on-eol 1 --quiet "$img" 2>/dev/null && echo 1 || echo 0
  done | grep -c 1 || true)
  echo "docker_image_eol $EOL"
} > "$OUT"
```

```ini
# /etc/cron.d/docker-security-metrics
*/5 * * * * root /usr/local/bin/docker-security-metrics.sh
```

Стек Prometheus/Grafana/Alertmanager — в [devsecops_monitoring.md](../../CI-CD/DevSecOps/devsecops_monitoring.md); данный экспортёр добавляет Docker-security метрики в тот же стек.

### Сценарий 5: drift detection as cron job

```bash
#!/bin/bash
# /usr/local/bin/docker-drift-check.sh
# Сравнивает running-контейнеры с задекларированным образом в registry

REGISTRY="my-registry.example.com:5000"
ALERT_WEBHOOK="http://alertmanager:9093/api/v2/alerts"

docker ps --format '{{.ID}} {{.Image}}' | while read cid img; do
  declared_digest=$(docker inspect --format '{{index .Image}}' "$cid")
  actual_digest=$(docker images --digests --format '{{if eq .Repository "'"${img%%:*}"'"}}{{.Tag}} {{.Digest}}{{end}}' | grep "^$(echo "$img" | sed 's/.*://') " | awk '{print $2}')
  if [ "$declared_digest" != "$actual_digest" ]; then
    echo "DRIFT: $cid expected=$actual_digest actual=$declared_digest"
    curl -s -X POST "$ALERT_WEBHOOK" -H 'Content-Type: application/json' \
      -d "[{\"labels\":{\"alertname\":\"DockerImageDrift\",\"container\":\"$cid\",\"severity\":\"warning\"},\"annotations\":{\"summary\":\"Image drift: $cid\"}}]"
  fi
done
```

### Сценарий 6: security SLO/SLA

| Метрика | SLO / SLA | Источник | Частота |
| :--- | :--- | :--- | :--- |
| % образов, просканированных в CI | 100% | CI pipeline | каждая сборка |
| % образов production с валидной подписью | 100% | `cosign verify` | ежедневно |
| EOL-образов в production | 0 | `trivy --exit-on-eol` | ежедневно |
| Привилегированных контейнеров | 0 | `docker inspect` | ежедневно |
| CIS Docker Benchmark score | ≥ 90% | docker-bench-security | еженедельно |
| MTTR Critical CVE | < 24 ч | incident log | по инцидентам |
| MTTR High CVE | < 7 дней | incident log | по инцидентам |
| Drift rate | < 5% | скрипт drift detection | ежедневно |

### Сценарий 7: парсинг docker-bench-security JSON в CI

```bash
# Запуск с JSON-логом
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -v /etc:/etc:ro -v /var/lib:/var/lib:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /usr/lib/systemd:/usr/lib/systemd:ro \
  -v /usr/bin/containerd:/usr/bin/containerd:ro \
  -v /usr/bin/runc:/usr/bin/runc:ro \
  docker/docker-bench-security -l json -o /tmp/bench.json

# Только Warning-проверки
jq -r '.tests[] | select(.result == "WARN") | "\(.id) \(.desc)"' /tmp/bench.json

# Итоговый score
jq -r '"Checks: \(.total_checks), Pass: \(.score), Score: \(.score * 100 / .total_checks | floor)%"' /tmp/bench.json
```

## Операции и команды

### Сбор метрик

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `docker ps -q \| xargs docker inspect --format '{{.HostConfig.Privileged}}'` | Число привилегированных контейнеров | Число (цель: 0) |
| `docker ps -q \| xargs docker inspect --format '{{.Config.User}}'` | Число контейнеров от root | Число (цель: 0) |
| `docker ps -q \| xargs docker inspect --format '{{.HostConfig.ReadonlyRootfs}}'` | Число контейнеров с read-only rootfs | Число (цель: 100%) |
| `trivy image --exit-code 1 --exit-on-eol 1 --severity CRITICAL <image>` | Сканирование + EOL check | exit 0 или WARN/ERROR |
| `cosign verify --key cosign.pub <image>` | Проверка подписи | `Verification OK` |
| `docker images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}}'` | Пининг по digest | Список digest-ов |
| `docker-bench-security -l json -o bench.json` | CIS score | JSON с `score` и `total_checks` |
| `docker events --since 1h --format '{{json .}}' \| jq 'select(.Action=="exec_start")'` | exec-события | JSON-события или пусто |
| `docker system df --format json` | Использование диска | JSON с Reclaimable |
| `docker stats --no-stream --format json` | Снапшот ресурсов | JSON с CPU/RAM/NetIO |

### Парсинг и агрегация

```bash
# Общее число контейнеров
docker ps -q | wc -l

# % non-root
total=$(docker ps -q | wc -l)
root=$(docker ps -q | xargs -r docker inspect --format '{{.Config.User}}' | grep -c '^$')
echo "non-root%: $(( (total - root) * 100 / total ))%"

# Drift rate (упрощённо: сравнение digest)
# см. Сценарий 5

# EOL count
trivy image --exit-on-eol 1 --quiet $(docker images --format '{{.Repository}}:{{.Tag}}' | head -20) 2>/dev/null | grep -c EOL || true
```

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `% signed` < 100% в production | Образы собраны вне CI или без Cosign | Проверить pipeline: `cosign sign` перед push; найти неподписанные образы через `cosign verify` |
| `% non-root` низкий | Базовые образы запускаются от root | `USER` в Dockerfile (см. [container_hardening.md](./container_hardening.md)); non-root образы (Distroless, Chainguard) |
| Drift rate растёт | Ручные `docker update`/`docker exec` | Запретить ручные изменения; конфигурация только через Compose/CI; аудит `docker events` |
| CIS score < 90% | Дефекты конфигурации демона/хоста | Отчёт docker-bench-security; исправить по [docker_bench_cis.md](./docker_bench_cis.md) |
| `cosign verify` не находит подпись | Реестр не поддерживает OCI 1.1 Referrers | Обновить Harbor до 2.11+; для старых — `--legacy-include-operations` |
| Trivy: 0 CVE на старом образе | EOL-ОС, пакеты вне базы, `--exit-on-eol` отсутствует | Добавить `--exit-on-eol 1`; проверьте дату EOL на endoflife.date |
| Метрики не появляются в Prometheus | textfile collector не настроен или нет прав | Проверить путь `/var/lib/node_exporter/textfile_collector/` и права на `.prom` файл |
| `manifest unknown` | Тег удалён retention или GC ещё не отработал | Проверить retention policy; запустить GC; использовать digest (см. [cleanup_gc_strategies.md](../Docker_fs/cleanup_gc_strategies.md)) |

## Граничные случаи

* **Docker Content Trust retirement:** DCT/Notary v1 устарел, `notary.docker.io` отключается 08.12.2026, сертификаты DOI официальных образов истекают с 08.08.2025. Удалите `DOCKER_CONTENT_TRUST=1` из окружения; мигрируйте на Cosign/Notation. Метрика `% signed` считается по Cosign/Notation.
* **Multi-arch подписи:** подпись привязывается к каждому child-образу манифест-листа отдельно; `cosign verify` проверяет только выбранный клиентом манифест (обычно amd64). Для multi-arch — проверяйте все архитектуры.
* **Air-gapped / офлайн-реестры:** публичный Sigstore недоступен; используйте self-hosted Fulcio/Rekor или ключ-based подпись (Cosign `--key`). Trivy — с `--registry-config` и air-gapped DB.
* **Self-signed TLS и Cosign:** Cosign может отказаться подписывать образ в реестре с self-signed сертификатом; добавьте CA в `SSL_CERT_FILE` или system trust store.
* **Rootless Docker:** `docker inspect` и `docker events` работают через `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock`; cron-скрипты должны иметь доступ к user-runtime директории.
* **Docker-in-Docker (DinD):** drift detection из outer-хоста не видит inner-контейнеры; используйте outer Docker socket или sidecar-подход.
* **Registry GC и 2-часовое окно:** Harbor GC не удаляет артефакты, загруженные за последние 2 часа; остановка GC не восстанавливает удалённое.
* **Trivy CVE-2026-33634:** уязвимость сканера, приводящая к компрометации образов. Фиксируйте версию Trivy ≥ 0.70.1; обновляйте при выходе CVE.

## Лучшие практики

1. **Метрики — из CI, не вручную.** % scanned/signed/pinned/non-root считаются в pipeline, а не разовыми проверками.
2. **SLO по MTTR** — Critical < 24 ч, High < 7 дней; фиксировать время обнаружения и устранения в incident log.
3. **Drift — метрика, а не разовая проверка.** Ежедневный сбор; рост drift rate — сигнал к запрету ручных изменений.
4. **CIS score — еженедельно.** Автозапуск docker-bench-security; деградация score — блокер релиза.
5. **Единый стек.** Docker-метрики отправлять в тот же Prometheus/Grafana, что и общие DevSecOps-метрики — не плодить отдельные системы.
6. **Алертинг на отклонение от SLO** — через Alertmanager (примеры алертов — в [devsecops_monitoring.md](../../CI-CD/DevSecOps/devsecops_monitoring.md#пример-2-security-alerting-через-alertmanager)).
7. **Trivy ≥ 0.70.1** — фиксируйте версию в CI из-за CVE-2026-33634.
8. **Cosign keyless или Notation** — подписи без управления ключами; OCI 1.1 Referrers для хранения attestations.
9. **Immutable tags** для release-тегов; пининг по digest в манифестах деплоя.
10. **RBAC и робот-аккаунты** для CI с expiration и minimal permissions; аудит пуш/pull в SIEM.
11. **EOL-образы — 0 в production.** `--exit-on-eol` в CI; политика максимального возраста 90 дней (см. [image_freshness_policy.md](./image_freshness_policy.md)).
12. **Network isolation:** registry доступен только из доверенных подсетей (CI/CD, K8s nodes); rate limiting на ingress; firewall rules (см. [registry_security.md](./registry_security.md)).

## Дополнительная информация

**Связанные документы:**

- [DevSecOps monitoring](../../CI-CD/DevSecOps/devsecops_monitoring.md) — SSoT общих метрик и стека мониторинга.
- [Docker Bench CIS](./docker_bench_cis.md) — проверка конфигурации.
- [Подпись и верификация образов](./image_signature_and_verification.md) — SSoT: Cosign, Notation, Kyverno, VSA.
- [Политика свежести образов](./image_freshness_policy.md) — SSoT: EOL-метрики, Renovate.
- [Сканирование уязвимостей](./vulnerability_scanning.md) — SSoT: Trivy, Grype, Copacetic.
- [Укрепление контейнеров](./container_hardening.md) — non-root, read-only, capabilities.
- [Безопасность реестров](./registry_security.md) — RBAC, аудит, network hardening.
- [Compliance-фреймворки](./compliance_frameworks.md) — PCI DSS, ISO 27001, SOC 2, EU CRA.
- [Нативные метрики Docker](../Docker_metrics/docker_native_metrics.md) — docker stats, PSI, cgroups.
- [Интеграция Docker с Prometheus](../Docker_metrics/docker_prometheus_integration.md) — Engine Metrics 9323, docker_sd_config.
- [Runtime-мониторинг](./runtime_monitoring.md) — Falco, auditd, Tetragon, drift prevention.
- [GC и retention](../Docker_fs/cleanup_gc_strategies.md) — очистка registry и Docker Engine.

**Инструменты:** `trivy` (≥ 0.70.1), `cosign` (v3.x), `notation` (v1.x), `docker-bench-security`, `jq`, `curl`, Prometheus textfile collector, Node Exporter, cAdvisor.
