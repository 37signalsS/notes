# FIPS 140-2 и Docker

**Актуально для:** Mirantis Container Runtime (MCR) 29.2.x — FIPS 140-2 validated (Linux) и FIPS 140-3 validated (Windows Server); Docker Engine 29.x CE — без FIPS-модуля; RHEL 9.x/10.x, Oracle Linux 9.x/10.x, Ubuntu 22.04/24.04/26.04. FIPS 140-2 Certificate #3304 sunset date — 21 сентября 2026; FIPS 140-3 Certificate #5195 (DEKRA, Mirantis Cryptographic Module) — с 13 марта 2026. Go boringcrypto FIPS — в [go.md](../Dockerfile/Docker_best_practices/go.md).

## Определения

**FIPS 140-2** — американский федеральный стандарт (NIST CMVP) для криптографических модулей Level 1. Валидация подтверждает, что реализация криптоалгоритмов прошла аккредитованное тестирование. Требуется для U.S. Federal (FISMA), а также часто для HIPAA, PCI DSS в регулируемых отраслях. Sunset date: 21 сентября 2026 (перемещение в Historical List).

**FIPS 140-3** — преемник FIPS 140-2 (ISO/IEC 19790/24759). Активная валидация с 2020 года; NIST рекомендует использовать 140-3 модули для новых закупок. Mirantis Cryptographic Module — Certificate #5195 (DEKRA, 13 марта 2026, sunset 2029).

**FIPS mode** — режим работы, при котором используются только FIPS-validated алгоритмы и модули. Включается на уровне ОС (kernel boot param `fips=1`) и/или на уровне приложения. В MCR FIPS mode включает `fips` в `Security Options` демона.

**Криптомодуль** — реализация криптофункций (библиотека), прошедшая валидацию CMVP с номером сертификата и опубликованной Security Policy.

## Предварительные требования

**Среда:**
- Linux-хост (RHEL 9.x/10.x, Oracle Linux 9.x/10.x, Ubuntu 22.04/24.04/26.04) или Windows Server 2022/2025 для MCR FIPS 140-3.
- Linux-ядро с поддержкой FIPS mode (`CONFIG_CRYPTO_USER_API_HASH` и `CONFIG_CRYPTO_USER_API_SKCIPHER`).
- BIOS/UEFI с включённым Secure Boot (рекомендуется, но не обязательно).
- Docker Engine 29.x CE для альтернативных сценариев; MCR 29.2.x для полной FIPS-валидации.

**Пакеты (RHEL/Oracle Linux):**
```bash
sudo dnf install -y yum-utils device-mapper-persistent-data lvm2
# MCR repo:
sudo yum-config-manager --add-repo https://download.mirantis.com/mcr/stable-29.2.repo
# Для FIPS:
sudo dnf install -y moby-engine+fips containerd+fips docker-ce-cli+fips
# Проверка:
docker info --format '{{.SecurityOptions}}'
# → fips,seccomp,apparmor,no-new-privileges
```

**Пакеты (Ubuntu/Debian):**
```bash
sudo apt-get install -y ca-certificates curl gnupg lsb-release
# MCR repo:
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.mirantis.com/mcr/stable-29.2/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/mirantis.gpg
echo "deb [signed-by=/etc/apt/keyrings/mirantis.gpg] https://download.mirantis.com/mcr/stable-29.2/ $(lsb_release -cs) stable-29.2" | sudo tee /etc/apt/sources.list.d/mirantis.list
# Для FIPS:
sudo apt-get update && sudo apt-get install -y moby-engine+fips containerd+fips docker-ce-cli+fips
```

**Ядро и FIPS mode (Linux):**
```bash
# Проверка поддержки FIPS в ядре:
cat /boot/config-$(uname -r) | grep -i fips
# → CONFIG_CRYPTO_FIPS=y

# Включение FIPS mode (перманентно):
sudo grubby --update-kernel=ALL --args="fips=1"
# Или вручную в /etc/default/grub:
# GRUB_CMDLINE_LINUX="... fips=1"
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
sudo reboot

# Проверка после загрузки:
cat /proc/sys/crypto/fips_enabled
# → 1
```

**Важно:** FIPS mode хоста (`fips=1`) — обязательное условие для MCR FIPS. Без него FIPS-сборка MCR откажется стартовать или не активирует криптомодуль.

## Базовые концепции

### Ключевой факт: Docker CE не FIPS-валидирован

Docker Engine CE (проект Moby) **не имеет FIPS 140-2/140-3 validated криптомодуля**. FIPS-валидированный модуль доступен только в коммерческом **Mirantis Container Runtime (MCR)** — продолжателе Docker Engine Enterprise:

| Продукт | FIPS 140-2 | FIPS 140-3 | Комментарий |
| :--- | :--- | :--- | :--- |
| Docker Engine CE | Нет | Нет | Криптофункции не валидированы CMVP |
| Mirantis Container Runtime (MCR) 29.x | Да — Certificate #3304, Mirantis Crypto Library v1.0, Level 1 | Да — Certificate #5195, Mirantis Cryptographic Module, Level 1 (Windows Server) | Валидированы: ID hashes, Swarm Raft log (Docker Secrets/Configs), Swarm overlay networks (control plane), Swarm mTLS, TLS binding сокета демона. Linux: FIPS 140-2 через канал `stable-29.2/fips`. Windows: FIPS 140-3 через `stable-29.2/fips`. |
| Mirantis Kubernetes Engine (MKE) | Нет | Нет | FIPS не поддерживается |
| Mirantis Secure Registry (MSR) | Нет | Нет | FIPS не поддерживается |

**Важно:** FIPS 140-2 Certificate #3304 имеет sunset date 21 сентября 2026. После этой даты сертификат перемещается в Historical List; новые развёртывания должны ориентироваться на FIPS 140-3 или использовать альтернативы для CE. MCR 29.x — последняя линейка с активной поддержкой FIPS-каналов.

**Ограничения MCR FIPS:**
- Linux: RHEL 9.x/10.x, Oracle Linux 9.x/10.x/8.6, Ubuntu 22.04/24.04/26.04 (по MCR 29.2 Compatibility Matrix). FIPS-режим требует включения FIPS на хосте.
- Windows: Windows Server 2022/2025.
- MKE и MSR FIPS не поддерживаются.

### Активация FIPS в MCR

1. Включить FIPS mode на хосте (Linux: `fips=1` в параметрах ядра GRUB/`grubby`, перезагрузка; Windows: FIPS mode через групповые политики).
2. Установить FIPS-сборку MCR из канала `stable-29.2/fips`. Версии пакетов имеют суффикс `+fips`.
3. MCR автоматически использует валидированный модуль при наличии `fips` в `Security Options`.
4. Явная активация: `DOCKER_FIPS=1` в drop-in systemd (`/etc/systemd/system/docker.service.d/fips-module.conf`).
5. Проверка: `docker info --format '{{.SecurityOptions}}'` → должен содержать `fips`.
6. Отключение FIPS **в Docker** (не на хосте): `DOCKER_FIPS=0` в том же drop-in; перезапуск демона.

### Альтернативы для Docker CE

Если требование FIPS касается приложения, а не самого Engine:

- **FIPS-enabled host OS** (RHEL/Oracle Linux/Ubuntu с `fips=1`): хостовые криптобиблиотеки валидированы, но криптофункции самого Docker — нет. Удовлетворяет требованиям, где валидация требуется для данных в transit/at rest на уровне ОС.
- **FIPS-validated base images** (Red Hat UBI 9/10): приложение внутри контейнера использует валидированные криптобиблиотеки (OpenSSL 3.x FIPS provider). Убедитесь, что образ собран для целевого release RHEL.
- **Go boringcrypto FIPS mode** — для Go-приложений: сборка с `GOEXPERIMENT=boringcrypto` и FIPS-валидированным модулем (см. [go.md](../Dockerfile/Docker_best_practices/go.md)).
- **OpenSSL FIPS provider** (OpenSSL 3.x) — для приложений на C/C++/Python.

**Не путать:** FIPS mode хоста (системная настройка) и FIPS-валидация Docker Engine (свойство продукта). Первое включаемо на любом Linux, второе — только в MCR. После 21 сентября 2026 FIPS 140-2 сертификаты перемещаются в Historical List; для новых проектов выбирайте FIPS 140-3 (MCR на Windows) или подтверждайте соответствие через хост + UBI.

## Практические сценарии

### Сценарий 1: проверка FIPS mode на хосте

```bash
# Состояние FIPS на хосте
cat /proc/sys/crypto/fips_enabled
# → 1 (FIPS включён)

# Или через sysctl
sysctl crypto.fips_enabled
# → crypto.fips_enabled = 1

# Проверка параметра загрузки ядра
cat /proc/cmdline
# → ... fips=1 ...

# Проверка FIPS через docker info (MCR):
docker info --format '{{.SecurityOptions}}'
# → fips,seccomp,apparmor,no-new-privileges
```

### Сценарий 2: включение DOCKER_FIPS=1 (MCR)

```bash
# systemd drop-in для демона
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/fips-module.conf <<'EOF'
[Service]
Environment=DOCKER_FIPS=1
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker

# Проверка
sudo systemctl show docker --property=Environment
# → Environment=DOCKER_FIPS=1

# Проверка FIPS в Security Options:
docker info --format '{{.SecurityOptions}}'
# → fips,seccomp,apparmor,no-new-privileges
```

Для отключения FIPS в Docker (с сохранением FIPS на хосте) — то же место, значение `DOCKER_FIPS=0`.

### Сценарий 3: FIPS-validated base image (UBI)

```dockerfile
# Red Hat UBI 9/10 — криптобиблиотеки из FIPS-validated криптомодуля RHEL
FROM registry.redhat.io/ubi9/ubi-minimal:latest
# Для RHEL 10 используйте ubi10/ubi-minimal

# Проверка FIPS-провайдера OpenSSL внутри контейнера
RUN openssl list -providers
# → providers:
# →   default
# →   fips (при fips=1 на хосте и FIPS-сборке)
```

### Сценарий 4: compliance-аудит (требование FIPS 140-2/140-3)

**Требование:** «Шифрование данных в transit и at rest должно использовать FIPS 140-2/140-3 validated модули».

**Решение:**
1. Engine: MCR 29.2.x из канала `stable-29.2/fips` с `DOCKER_FIPS=1` (валидированы TLS демона, Swarm mTLS, Raft log). Linux — FIPS 140-2 (cert #3304, sunset 21.09.2026); Windows Server — FIPS 140-3 (cert #5195, DEKRA, 13.03.2026).
2. Приложения: UBI 9/10 base images с OpenSSL 3.x FIPS provider или Go boringcrypto.
3. TLS: версии 1.2+ с FIPS-approved шифрами (проверка: `openssl ciphers -s -tls1_2 -tls1_3`).
4. Для Docker CE: FIPS mode хоста + UBI base images + документация scope соответствия.
5. Документировать scope валидации: что именно покрывает сертификат (см. Security Policy CMVP). Для PCI DSS v4.0.1, ISO 27001, SOC 2 (2026) и EU CRA — хранить evidence ≥ 12 месяцев.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `fips_enabled = 0` | FIPS не включён на хосте | `fips=1` в GRUB (`GRUB_CMDLINE_LINUX`), `grub2-mkconfig`, перезагрузка |
| В `docker info` нет `fips` в `SecurityOptions` | Установлен CE или не-FIPS сборка MCR | Установить `moby-engine+fips` из `stable-29.2/fips`; проверить версию `docker version` — суффикс `+fips` |
| MCR не стартует с FIPS | ОС вне Compatibility Matrix или `fips=1` отсутствует | Проверить MCR 29.2 Compatibility Matrix (RHEL/Oracle Linux/Ubuntu/Windows); убедиться в `fips=1` на Linux |
| Контейнер не использует FIPS-крипто | Base image без FIPS-модулей | UBI 9/10/FIPS-validated образы; проверить `openssl list -providers` |
| «FIPS» в Docker CE не работает | CE не имеет FIPS-модуля | MCR для валидированного Engine; для CE — FIPS на уровне хоста и образов |
| MKE/MSR не работают с FIPS | FIPS не поддерживается MKE/MSR | Только MCR поддерживает FIPS 140-2/140-3; планировать замену компонентов |
| OpenSSL внутри контейнера: `disabled` provider | Хост без `fips=1` или образ без FIPS-OpenSSL | Включить FIPS на хосте; пересобрать образ с FIPS-OpenSSL |
| Sunset FIPS 140-2 (21.09.2026) | Сертификат #3304 перемещён в Historical List | Для Linux использовать FIPS-валидацию хоста + UBI; для Windows — MCR FIPS 140-3 (cert #5195) |

## Лучшие практики

1. **Требование FIPS для Engine → MCR**, не Docker CE. CE не имеет валидированного криптомодуля. Используйте MCR 29.2.x с каналом `stable-29.2/fips`; версии имеют суффикс `+fips`.
2. **Проверять `docker info --format '{{.SecurityOptions}}'`** — наличие `fips` подтверждает, что MCR FIPS сборка активна, а не только `fips_enabled=1` на хосте.
3. **Проверять `/proc/sys/crypto/fips_enabled`** — FIPS mode должен быть включён на хосте до запуска MCR.
4. **FIPS-validated base images** (UBI 9/10) для приложений — валидация приложения не следует из FIPS mode хоста.
5. **Документировать scope** — сертификат #3304 (FIPS 140-2, sunset 21.09.2026) покрывает TLS демона, Swarm, ID hashes; сертификат #5195 (FIPS 140-3, Windows) — аналогичный scope. Не распространяется на MKE/MSR и приложения.
6. **Не смешивать уровни** — FIPS mode хоста, FIPS-валидация Engine и FIPS-валидация приложения — три независимых утверждения.
7. **Альтернативы** — Go boringcrypto и OpenSSL 3.x FIPS provider для приложений, где MCR недоступен.
8. **Сценарий sunset FIPS 140-2.** После 21.09.2026 новые проекты должны выбирать FIPS 140-3 (MCR Windows) или подтверждать соответствие через хост + UBI + документальный evidence для регуляторов.
9. **Версионировать FIPS-сборки.** Пакеты с суффиксом `+fips` должны обновляться вместе с ядром хоста; фиксируйте канал `stable-29.2/fips` в deployment-инструментарии (Ansible/Chef).
10. **Тестировать в CI** на хосте с `fips=1` (QEMU/KVM или dedicated runner), иначе regression в FIPS-режиме пропустится.

### Ограничения и граничные случаи

- **FIPS 140-2 sunset (21.09.2026).** После этой даты сертификат #3304 перемещается в Historical List. Федеральные агентства США могут перестать принимать новые закупки по 140-2; планируйте миграцию на FIPS 140-3 (MCR Windows) или подтверждение соответствия через хост + UBI + документацию.
- **FIPS 140-3 в MCR — только Windows Server (на текущий момент).** На Linux доступен только FIPS 140-2 (cert #3304). Для Linux-сред, требующих 140-3, используйте альтернативы: FIPS-enabled хост + UBI base images + OpenSSL FIPS provider.
- **Kernel `fips=1` — несовместим с某些 модулями.** Некоторые DKMS-модули (VirtualBox, certain NVIDIA drivers) не работают в FIPS mode из-за ограничений на MD5/SHA-1 в модулях. Тестируйте драйверы до включения в production.
- **UBI base images и register mirror.** FIPS-среды часто запрещают не-FIPS шифры. Убедитесь, что registry mirror (`registry.redhat.io`) доступен и не блокируется corporate firewall; используйте `skopeo` с FIPS-совместимыми TLS-шифрами.
- **Docker CE в FIPS-среде.** Docker CE работает, но `Security Options` не содержит `fips`. Приложения могут падать, если ожидают FIPS-провайдер OpenSSL; проверяйте `openssl list -providers` и явно указывайте `default` provider.
- **Rootless mode и FIPS.** Rootless Docker не тестируется Mirantis в FIPS-среде. Если требуется rootless + FIPS — используйте отдельный hardened namespace container runtime (podman) с FIPS-validated крипто.
- **Windows Server FIPS mode.** Включение FIPS через групповые политики (Computer Configuration → Administrative Templates → System → FIPS) требует перезагрузки; MCR FIPS 140-3 установится автоматически из `stable-29.2/fips` канала.

## Дополнительная информация

**Связанные документы:**

- [Защита хоста и демона](./host_daemon_hardening.md) — конфигурация демона.
- [Compliance-фреймворки](./compliance_frameworks.md) — PCI DSS, ISO 27001.
- [Go-образы и FIPS-режим](../Dockerfile/Docker_best_practices/go.md) — boringcrypto.
- [Подпись и верификация образов](./image_signature_and_verification.md) — Notation с HSM (FIPS-валидированные HSM).

**Внешние ресурсы:**

- [NIST CMVP Certificate #3304](https://csrc.nist.gov/CSRC/media/projects/cryptographic-module-validation-program/documents/security-policies/140sp3304.pdf) — Security Policy Mirantis Crypto Library (FIPS 140-2).
- [NIST CMVP Certificate #5195](https://csrc.nist.gov/projects/cryptographic-module-validation-program/certificate/5195) — Mirantis Cryptographic Module (FIPS 140-3, DEKRA, 13.03.2026).
- [MCR FIPS 140-2 (Linux)](https://docs.mirantis.com/mcr/29/install/mcr-linux/fips-140-2-cryptographic-module-support.html) — активация, Compatibility Matrix, DOCKER_FIPS.
- [MCR FIPS 140-3 (Windows Server)](https://docs.mirantis.com/mcr/29/install/mcr-windows.html) — FIPS 140-3 для Windows Server 2022/2025.
- [MCR 29.2 Compatibility Matrix](https://docs.mirantis.com/mcr/29/compat-matrix/mcr-29.2-compatibility-matrix.html) — поддерживаемые ОС для FIPS-сборок.

**Инструменты:** `sysctl`, `openssl list -providers`, `cat /proc/cmdline`, `grubby`, `docker info`, `skopeo`.
