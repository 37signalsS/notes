# Сканирование безопасности и compliance образов ВМ

В данном файле описывается автоматизированное тестирование образов ВМ на уязвимости, соответствие стандартам безопасности (CIS Benchmark, DISA STIG) и проверка состава ПО (SBOM) перед развёртыванием в продакшен. Hardening при сборке описан в [Автоматизации сборки образов](./image_automation.md).

## Определения

**CIS Benchmark (Center for Internet Security)** — набор рекомендаций по настройке безопасности для различных платформ. Уровень 1 — базовые проверки, уровень 2 — расширенные (включая аудит). Используется как стандарт для hardened-образов.

**DISA STIG (Security Technical Implementation Guide)** — военный стандарт безопасности США. Более строгий, чем CIS. Требуется для government/military инфраструктур.

**SBOM (Software Bill of Materials)** — машиночитаемый список всех компонентов (пакеты, библиотеки, зависимости) в образе. Используется для отслеживания уязвимостей (CVE) и лицензионных рисков.

**CVE (Common Vulnerabilities and Exposures)** — база данных известных уязвимостей. Каждая уязвимость имеет идентификатор CVE-YYYY-NNNNN и оценку CVSS (0-10).

**CVSS (Common Vulnerability Scoring System)** — стандарт оценки серьезности уязвимостей. Критические: 9.0-10.0, Высокие: 7.0-8.9, Средние: 4.0-6.9, Низкие: 0.1-3.9.

**Trivy** — open-source сканер уязвимостей от Aqua Security. Поддерживает сканирование OCI-образов, файловых систем, SBOM. Стандарт индустрии для DevSecOps.

**OpenSCAP** — фреймворк для аудита соответствия стандартам безопасности (CIS, DISA STIG, PCI-DSS). Генерирует OVAL/CVE-отчёты.

** Lynis** — инструмент аудита безопасности Linux-систем. Проверяет конфигурацию, права доступа, сетевые настройки, криптографию.

**Image Compliance** — проверка образа на соответствие политикам безопасности до развёртывания в продакшен. Включает: сканирование CVE, проверку пакетов, аудит конфигурации.

## Базовые концепции

### Архитектура пайплайна безопасности

```
┌─────────────────────────────────────────────────────────┐
│  Этап 1: Сборка (Packer)                                │
│  ├── CIS Benchmark hardening                            │
│  └── Установка агентов (auditd, ossec)                  │
├─────────────────────────────────────────────────────────┤
│  Этап 2: Сканирование уязвимостей                       │
│  ├── Trivy: CVE в пакетах ОС                            │
│  ├── Lynis: аудит конфигурации                          │
│  └── OpenSCAP: CIS/DISA STIG compliance                 │
├─────────────────────────────────────────────────────────┤
│  Этап 3: SBOM и лицензии                                │
│  ├── Trivy SBOM (CycloneDX/SPDX)                       │
│  └── Проверка лицензий (FOSSA, license-checker)         │
├─────────────────────────────────────────────────────────┤
│  Этап 4: Валидация                                      │
│  ├── serverspec/testinfra                               │
│  ├── Boot test (запуск ВМ из образа)                    │
│  └── Network connectivity test                          │
├─────────────────────────────────────────────────────────┤
│  Этап 5: Публикация (если все тесты пройдены)           │
│  ├── Подпись образа (cosign/skopeo)                     │
│  └── Загрузка в реестр/хранилище                        │
└─────────────────────────────────────────────────────────┘
```

### Матрица инструментов

| Инструмент | Фокус | Формат образа | Офлайн | Интеграция CI/CD |
| :--- | :--- | :--- | :--- | :--- |
| **Trivy** | CVE (пакеты, deps) | OCI, dir, rootfs | Да (trivy db) | GitLab, GitHub, Jenkins |
| **OpenSCAP** | CIS/DISA STIG compliance | OVAL, xccdf | Да | Ansible, cron |
| **Lynis** | Аудит конфигурации | Запущенная система | Нет | SSH, Ansible |
| **Grype** | CVE (контейнеры) | OCI | Да | GitHub Actions |
| **Syft** | SBOM generation | OCI, dir | Да | CI/CD |
| **Cosign** | Подпись образов | OCI | Да | CI/CD |

## Практические сценарии

### Сценарий 1: Trivy — сканирование CVE в образе ВМ

Trivy работает с raw-директориями (monted image) или OCI-образами. Для qcow2-образов ВМ нужно примонтировать раздел.

```bash
# 1. Установка Trivy
sudo apt-get install -y trivy
# Или через Docker:
docker pull aquasec/trivy:0.74.0

# 2. Монтирование образа ВМ для сканирования
MOUNT_DIR=$(mktemp -d)
sudo modprobe nbd max_part=8
sudo qemu-nbd --connect=/dev/nbd0 /var/lib/libvirt/images/web-server.qcow2
sudo partprobe /dev/nbd0
sudo mount /dev/nbd0p1 "$MOUNT_DIR"

# 3. Сканирование файловой системы
trivy rootfs "$MOUNT_DIR" \
  --severity HIGH,CRITICAL \
  --format json \
  --output trivy-results.json

# 4. Сканирование с учетом исправлений
trivy rootfs "$MOUNT_DIR" \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1

# 5. Генерация SBOM
trivy rootfs "$MOUNT_DIR" \
  --format cyclonedx \
  --output sbom.json

# 6. Очистка
sudo umount "$MOUNT_DIR"
sudo qemu-nbd --disconnect /dev/nbd0
rmdir "$MOUNT_DIR"
```

**Интеграция в CI/CD (GitLab):**
```yaml
scan-vm-image:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    # Монтирование и сканирование
    - |
      modprobe nbd max_part=8
      qemu-nbd --connect=/dev/nbd0 output-ubuntu/*.qcow2
      partprobe /dev/nbd0
      mount /dev/nbd0p1 /mnt
    - trivy rootfs /mnt --severity HIGH,CRITICAL --exit-code 1
    - trivy rootfs /mnt --format cyclonedx --output sbom.json
  artifacts:
    paths:
      - sbom.json
    reports:
      container_scanning: trivy-results.json
  allow_failure: false
```

### Сценарий 2: OpenSCAP — CIS Benchmark compliance

```bash
# 1. Установка OpenSCAP
sudo apt-get install -y libopenscap8 ssg-debderived ssg-base ssg-ubuntu2404-ds

# Скачивание профилей (если нет в пакете)
 oscap info /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# 2. Сканирование на соответствие CIS Level 1
sudo oscap xccdf eval \
  --profile cis_level1 \
  --results cis-results.xml \
  --report cis-report.html \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# 3. Просмотр результатов
oscap xccdf generate report cis-results.xml > cis-report.html

# 4. Автоматическое исправление (remediation)
sudo oscap xccdf generate fix \
  --profile cis_level1 \
  --output remediation.sh \
  cis-results.xml

# Применение:
sudo bash remediation.sh
```

**Сканирование остановленного образа (offline):**
```bash
# 1. Монтирование образа
sudo qemu-nbd --connect=/dev/nbd0 /var/lib/libvirt/images/template.qcow2
sudo mount /dev/nbd0p1 /mnt

# 2. Сканирование с chroot
sudo oscap chroot /mnt xccdf eval \
  --profile cis_level1 \
  --results cis-results.xml \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# 3. Очистка
sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
```

### Сценарий 3: Lynis — аудит конфигурации

```bash
# 1. Установка Lynis
sudo apt-get install -y lynis

# 2. Быстрый аудит
sudo lynis audit system --quick

# 3. Полный аудит с отчётом
sudo lynis audit system --report-file /var/log/lynis-report.dat

# 4. Просмотр результатов
grep "hardening_index" /var/log/lynis-report.dat
# → hardening_index=72 (нужно > 65 для production)

# 5. Проверка конкретных тестов
sudo lynis show tests
# Показывает все доступные тесты

# 6. Сканирование через SSH (для проверки готового образа)
lynis audit system --tests-from-group "firewalls" --logfile /dev/stdout

# 7. Автоматический аудит в CI/CD
cat > /usr/local/sbin/lynis-ci.sh << 'SCRIPT'
#!/bin/bash
lynis audit system --quick --quiet
SCORE=$(grep "hardening_index" /var/log/lynis-report.dat | awk -F= '{print $2}')
if [ "$SCORE" -lt 65 ]; then
  echo "FAIL: Lynis score $SCORE < 65"
  exit 1
fi
echo "PASS: Lynis score $SCORE"
SCRIPT
```

### Сценарий 4: Генерация и проверка SBOM

```bash
# 1. Генерация SBOM через Syft
syft dir:/mnt -o cyclonedx-json > sbom-cyclonedx.json
syft dir:/mnt -o spdx-json > sbom-spdx.json

# 2. Проверка SBOM на известные уязвимости
grype sbom:sbom-cyclonedx.json \
  --fail-on high

# 3. Просмотр состава образа
cat sbom-cyclonedx.json | jq '.components[] | "\(.name)@\(.version)"'
# → "openssl@3.0.14"
# → "openssh-server@9.6p1"
# → "linux-image@6.8.0-40"

# 4. Поиск конкретной уязвимости
cat sbom-cyclonedx.json | jq '.components[] | select(.name | contains("openssl"))'
```

### Сценарий 5: Полный пайплайн сканирования

```yaml
# .gitlab-ci.yml — security scanning для VM images
stages:
  - build
  - scan
  - compliance
  - publish

variables:
  IMAGE_PATH: "output-ubuntu/*.qcow2"

build-image:
  stage: build
  script:
    - packer build packer/ubuntu-24.04.pkr.hcl
  artifacts:
    paths:
      - output-ubuntu/
    expire_in: 1 day

trivy-scan:
  stage: scan
  image: aquasec/trivy:0.74.0
  needs: [build-image]
  script:
    - modprobe nbd max_part=8
    - qemu-nbd --connect=/dev/nbd0 $IMAGE_PATH
    - partprobe /dev/nbd0 && mount /dev/nbd0p1 /mnt
    - trivy rootfs /mnt --severity HIGH,CRITICAL --exit-code 1
    - trivy rootfs /mnt --format cyclonedx --output sbom.json
  artifacts:
    paths: [sbom.json]

openscap-compliance:
  stage: compliance
  needs: [build-image]
  script:
    - modprobe nbd max_part=8
    - qemu-nbd --connect=/dev/nbd0 $IMAGE_PATH
    - mount /dev/nbd0p1 /mnt
    - oscap chroot /mnt xccdf eval \
        --profile cis_level1 \
        --results cis-results.xml \
        /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml
    - |
      # Проверка: все правила пройдены?
      FAILED=$(xmllint --xpath '//rule-result/result[fail]' cis-results.xml 2>/dev/null | wc -l)
      if [ "$FAILED" -gt 0 ]; then
        echo "FAIL: $FAILED CIS rules failed"
        exit 1
      fi
  artifacts:
    paths: [cis-results.xml]

publish-image:
  stage: publish
  needs: [trivy-scan, openscap-compliance]
  only: [main]
  script:
    - echo "All security checks passed. Publishing image."
    # Публикация в реестр/хранилище
```

### Сценарий 6: Периодическое сканирование существующих образов

```bash
#!/bin/bash
# scan-all-images.sh — сканирование всех шаблонов
set -euo pipefail

IMAGES_DIR="/var/lib/libvirt/images"
REPORT_DIR="/var/log/image-scan/$(date +%Y%m%d)"
mkdir -p "$REPORT_DIR"

for img in "$IMAGES_DIR"/*-template.qcow2; do
  [ -f "$img" ] || continue
  NAME=$(basename "$img" .qcow2)
  echo "=== Scanning: $NAME ==="
  
  MOUNT_DIR=$(mktemp -d)
  sudo qemu-nbd --connect=/dev/nbd0 "$img"
  sudo partprobe /dev/nbd0
  sudo mount /dev/nbd0p1 "$MOUNT_DIR"
  
  # Trivy
  trivy rootfs "$MOUNT_DIR" \
    --severity HIGH,CRITICAL \
    --format json \
    --output "$REPORT_DIR/${NAME}-trivy.json" 2>/dev/null || true
  
  # Lynis (быстрый)
  sudo lynis audit system --quick --quiet --logfile "$REPORT_DIR/${NAME}-lynis.log" 2>/dev/null || true
  
  sudo umount "$MOUNT_DIR"
  sudo qemu-nbd --disconnect /dev/nbd0
  rmdir "$MOUNT_DIR"
done

echo "Reports: $REPORT_DIR"
```

## Пороговые значения

| Проверка | Порог | Действие |
| :--- | :--- | :--- |
| **Trivy CRITICAL CVE** | 0 | Блокировать публикацию |
| **Trivy HIGH CVE** | 0 (ignore-unfixed допустим) | Блокировать или предупреждать |
| **CIS Benchmark score** | > 80% (Level 1) | Предупреждать, исправлять |
| **Lynis hardening index** | > 65 | Предупреждать |
| **SBOM: неизвестные пакеты** | 0 | Проверять вручную |

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Trivy: "no OS packages found"** | Образ не примонтирован или пустая ФС | Проверить mount point, убедиться что пакеты установлены |
| **OpenSCAP: "profile not found"** | Нет установленных SCAP-профилей | Установить `ssg-*` пакеты |
| **Lynis: score < 50** | Множество hardening-рекомендаций не выполнены | Запустить `lynis fix recommendations` |
| **CIS: fail на кастомных настройках** | CIS не учитывает особенности среды | Настроить tailoring file для игнорирования неприменимых правил |
| **SBOM: завышенный размер** | Слишком много зависимостей | Использовать minimal base image (Alpine, distroless) |

## Дополнительная информация

- [Автоматизация сборки образов](./image_automation.md) — Packer, CIS hardening, CI/CD.
- [Основные концепции](./basic_concepts.md) — форматы, шифрование,安全.
- [Безопасность KVM-хостов](../kvm/kvm_security_hardening.md) — sVirt, polkit, LUKS.
- [Trivy: Сканирование уязвимостей](../../Docker/Docker_security/vulnerability_scanning.md) — полное руководство по Trivy.
- [OpenVAS](../../Security/Tools/openvas_installation_and_usage.md) — сетевое сканирование.
