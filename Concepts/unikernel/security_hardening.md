# Безопасность и hardening Unikernel

**Актуально для:** Unikraft v0.21.0, KraftKit v0.12.15, Nanos (актуальная ветка), MirageOS v4.11.x, OSv v0.57.0; примеры для on-premise развёртываний

## Определения

**Безопасность и hardening юникернелов** — это комплекс мер, направленных на обеспечение конфиденциальности, целостности и доступности юникернел-инфраструктуры в on-premise среде. Включает сканирование образов, генерацию SBOM, подписание, применение MAC-профилей (AppArmor/SELinux), seccomp-ограничений и проверку соответствия регуляторным требованиям.

Базовая информация — в [Обзоре Unikernel](./unikernel_overview.md) и [Преимуществах и ограничениях](./unikernel_advantages_disadvantages.md).

## Основные концепции

### Модель угроз

Юникернел имеет минимальную поверхность атаки по дизайну, но остаётся уязвимым на уровне:
1. **Образ:** уязвимости в Library OS или зависимостях приложения.
2. **Хост:** компрометация KVM/QEMU или libvirt.
3. **Сеть:** атаки на TAP-интерфейсы, мосты, NAT.
4. **Снапшоты/образы:** утечка данных через неочищенные снапшоты.

### Принципы hardening

- **Immutable Infrastructure:** Образ не меняется после сборки. Любое изменение = новая версия.
- **Least Privilege:** Минимальные права для QEMU/VMM, минимальные драйверы в образе.
- **Defense in Depth:** Несколько слоёв защиты: MAC-профили, seccomp, сетевые политики, сканирование.
- **Supply Chain Security:** Проверка каждого этапа: сборка → сканирование → подпись → деплой.

## Практические сценарии

### 1. Сканирование образов

#### Trivy

```bash
# Установка Trivy
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

# Сканирование образа
trivy image --severity HIGH,CRITICAL /var/lib/libvirt/images/unikernels/my-service.qcow2

# Сканирование файловой системы (rootfs)
trivy rootfs --severity HIGH,CRITICAL ./build/

# Сканирование Git-репозитория
trivy repo --severity HIGH,CRITICAL https://github.com/myorg/my-service
```

#### Grype

```bash
# Установка Grype
curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin

# Сканирование
grype dir:/var/lib/libvirt/images/unikernels/ --only-fixed
```

### 2. Генерация SBOM

#### Syft (CycloneDX)

```bash
# Установка Syft
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# Генерация SBOM
syft /var/lib/libvirt/images/unikernels/my-service.qcow2 -o cyclonedx-json > sbom.cdx.json

# Проверка
cat sbom.cdx.json | jq '.components | length'
# → количество компонентов
```

#### Проверка SBOM в CI/CD

```yaml
# .gitlab-ci.yml
generate-sbom:
  stage: build
  image: anchore/syft:latest
  script:
    - syft /var/lib/libvirt/images/unikernels/my-service.qcow2 -o cyclonedx-json > sbom.cdx.json
    - grype sbom:sbom.cdx.json --only-fixed --fail-on high
  artifacts:
    paths:
      - sbom.cdx.json
```

### 3. Подписание образов

#### Cosign

```bash
# Генерация ключей
cosign generate-key-pair

# Подписание образа
cosign sign --key cosign.key /var/lib/libvirt/images/unikernels/my-service.qcow2

# Проверка подписи
cosign verify --key cosign.pub /var/lib/libvirt/images/unikernels/my-service.qcow2

# Keyless (Fulcio/Rekor)
COSIGN_EXPERIMENTAL=1 cosign sign /var/lib/libvirt/images/unikernels/my-service.qcow2
```

#### Верификация перед запуском

```bash
#!/bin/bash
# verify-and-run.sh
IMAGE="/var/lib/libvirt/images/unikernels/my-service.qcow2"

# Проверка подписи
if ! cosign verify --key cosign.pub "$IMAGE"; then
  echo "ERROR: Image signature verification failed"
  exit 1
fi

# Проверка SBOM
syft "$IMAGE" -o cyclonedx-json > /tmp/sbom-check.json
if grype sbom:/tmp/sbom-check.json --only-fixed --fail-on high; then
  echo "ERROR: Vulnerabilities found in SBOM"
  exit 1
fi

# Запуск
kraft run --headless --background -p 8080:80 "$IMAGE"
```

### 4. MAC-профили (AppArmor/SELinux)

Общая теория AppArmor и SELinux: [AppArmor — основы](../../Linux/Security/Mechanisms/AppArmor.md), [SELinux — основы](../../Linux/Security/Mechanisms/SELinux.md). Seccomp: [Seccomp — механизм изоляции](../../Linux/Security/Mechanisms/seccomp.md).

#### AppArmor для QEMU

```bash
# /etc/apparmor.d/usr.sbin.qemu-system-x86_64
#include <abstractions/base>
#include <abstractions/nameservice>

profile qemu-system-x86_64 /var/lib/libvirt/images/unikernels/*.qcow2 {
  # Разрешения на бинарник
  /usr/bin/qemu-system-x86_64 mr,
  /usr/bin/qemu-system-x86_64/* mr,

  # Доступ к образу
  /var/lib/libvirt/images/unikernels/*.qcow2 r,

  # Сеть (TAP-интерфейс)
  /sys/class/net/tap* r,
  /etc/qemu/** r,

  # Логи
  /var/log/unikernel/*.log w,

  # Запрет на всё остальное
  deny /var/lib/libvirt/images/** w,
  deny /etc/libvirt/** w,
  deny /home/** rw,
  deny /root/** rw,
}
```

```bash
# Применение профиля
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.qemu-system-x86_64

# Проверка
sudo aa-status | grep qemu
# → qemu-system-x86_64  confined
```

#### SELinux для QEMU

Общая теория: [SELinux — основы](../../Linux/Security/Mechanisms/SELinux.md). Ниже — модуль политики, специфичный для изоляции юникернел-инстанса.

```bash
# Генерация модуля
cat <<EOF > qemu-unikernel.te
module qemu-unikernel 1.0;

require {
  type qemu_t;
  type unikernel_image_t;
  type var_log_t;
  class file { read write open };
}

# Разрешения
allow qemu_t unikernel_image_t:file { read open };
allow qemu_t var_log_t:file { write open };
EOF

# Компиляция и установка
checkmodule -M -m -o qemu-unikernel.mod qemu-unikernel.te
semodule_package -o qemu-unikernel.pp -m qemu-unikernel.mod
sudo semodule -i qemu-unikernel.pp

# Проверка
sudo ausearch -m avc -ts recent | grep qemu
```

### 5. Seccomp-профили

Общая теория: [Seccomp — механизм изоляции](../../Linux/Security/Mechanisms/seccomp.md). Ниже — пример профиля для QEMU, ограничивающий syscalls юникернел-инстанса.

```bash
# Создание профиля
cat <<EOF > /etc/qemu/seccomp-unikernel.json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": ["read", "write", "open", "openat", "close", "ioctl", "mmap", "mprotect"],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": ["socket", "bind", "listen", "accept", "connect", "sendto", "recvfrom"],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": ["exit", "exit_group", "rt_sigaction", "rt_sigprocmask"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
EOF

# Запуск с seccomp
qemu-system-x86_64 \
  -seccomp /etc/qemu/seccomp-unikernel.json \
  -drive file=my-service.qcow2,if=virtio \
  -m 256 -nographic
```

### 6. Сетевые политики

#### iptables для юникернелов

```bash
# Создание отдельной цепочки
sudo iptables -N UNIKERNEL
sudo iptables -A FORWARD -j UNIKERNEL

# Правила для конкретного юникернела
sudo iptables -A UNIKERNEL -s 10.0.0.2 -p tcp --dport 53 -j ACCEPT
sudo iptables -A UNIKERNEL -s 10.0.0.2 -p udp --dport 53 -j ACCEPT
sudo iptables -A UNIKERNEL -s 10.0.0.2 -j DROP

# Логирование
sudo iptables -A UNIKERNEL -s 10.0.0.2 -j LOG --log-prefix "UNIKERNEL-DROP: "
```

### 7. Compliance-чеклисты

#### PCI DSS

- [ ] Минимизация сервисов: юникернел содержит только приложение + Library OS
- [ ] Изоляция: аппаратная изоляция через KVM
- [ ] Аудит: логирование всех операций `kraft run`, `ops run`, `xl create`
- [ ] Шифрование: TLS для трафика, шифрование дисков хоста

#### HIPAA

- [ ] Изоляция данных: каждый клиент = отдельный юникернел
- [ ] Шифрование: AES-256 для данных at-rest
- [ ] Аудит: centralized syslog, eBPF-трассировка
- [ ] Доступ: RBAC для libvirt/KubeVirt

#### SOC 2

- [ ] Иммутабельность: все образы имеют digest, хранятся в registry
- [ ] Change Management: все изменения через CI/CD
- [ ] Мониторинг: Prometheus + Grafana + алерты
- [ ] Документация: runbooks для типичных инцидентов

### 8. Supply Chain Security

Полный пайплайн:

```yaml
stages:
  - build
  - scan
  - sign
  - deploy

build-unikernel:
  stage: build
  script:
    - kraft build --target qemu --arch x86_64
    - kraft image list --json > image-manifest.json

scan:
  stage: scan
  script:
    - trivy image --severity HIGH,CRITICAL build/my-service-qemu-x86_64
    - syft build/my-service-qemu-x86_64 -o cyclonedx-json > sbom.cdx.json
    - grype sbom:sbom.cdx.json --only-fixed --fail-on high

sign:
  stage: sign
  script:
    - cosign sign --key cosign.key build/my-service-qemu-x86_64
    - cosign attest --predicate sbom.cdx.json --type cyclonedx build/my-service-qemu-x86_64

deploy:
  stage: deploy
  script:
    - verify-and-run.sh
```

## Валидация и проверка работоспособности

- **Сканирование:** `trivy image`, `grype dir` — нет критических CVE.
- **SBOM:** `syft` генерирует корректный CycloneDX/SPDX.
- **Подпись:** `cosign verify` возвращает success.
- **AppArmor/SELinux:** `aa-status`, `ausearch` — нет отказов.
- **Seccomp:** `dmesg | grep seccomp` — нет неразрешённых syscalls.
- **Сеть:** `iptables -L -n`, `nft list ruleset` — только разрешённые порты.
- **Libvirt audit:** `ausearch -m avc -ts recent`, `journalctl -u libvirtd` — нет неожиданных отказов.
- **QEMU capabilities:** `getpcaps $(pgrep qemu-system-x86_64)` — присутствуют только `CAP_IPC_LOCK`, `CAP_SYS_NICE`, `CAP_NET_ADMIN`, `CAP_NET_RAW`.
- **cgroups blkio:** `cat /sys/fs/cgroup/blkio/libvirt/<domain>/blkio.throttle.io_service_bytes` — лимиты применены.

## Устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **QEMU запускается без AppArmor/SELinux confinement** | Профиль не загружен, libvirt не integrates с LSM | `aa-status`, `sestatus`, `ps -eZ \| grep qemu` | Загрузить профиль, проверить `apparmor_parser -r`, проверить политику SELinux (`semodule -l \| grep qemu`) |
| **Seccomp блокирует легитимный syscall** | Слишком строгий профиль, не учтён архитектурный вызов | `dmesg \| grep seccomp`, `strace -f -e trace=seccomp qemu-system-x86_64 ...` | Добавить syscall в allow-лист, перезапустить с `SCMP_ACT_LOG` для сбора логов |
| **Trivy/Grype находят критические CVE в golden image** | Уязвимости в Library OS или статических зависимостях | `trivy image --format json`, `grype dir --only-fixed` | Пересобрать образ с обновлёнными зависимостями, обновить Library OS, повторить сканирование |
| **Cosign verify: certificate identity mismatch** | OIDC-claim не совпадает с политикой, или ключ устарел | `cosign verify --output text ...`, `cosign public-key --key cosign.pub` | Исправить `--certificate-identity`, обновить публичный ключ, для on-prem использовать key-based подпись вместо keyless |
| **Снапшот содержит данные из предыдущего запуска** | Образ не пересоздан, кэш QEMU не очищен | `virt-clone --check`, `qemu-img info --backing-chain` | Использовать immutable images (COW на read-only base), копировать образ для каждого запуска, настроить `libvirt` wipe on delete |
| **Guest не может открыть сокет / доступ к сети заблокирован** | AppArmor/SELinux блокирует `/sys/class/net/`, seccomp запрещает `socket` | `ausearch -m avc -ts recent`, `dmesg \| grep -i seccomp`, `iptables -L -n -v` | Добавить правило в профиль, разрешить syscall, проверить цепочку `UNIKERNEL` |
| **Низкая производительность после включения confinement** | `SCMP_ACT_ERRNO` на часто используемом syscall, AppArmor в complain режиме вызывает overhead | `perf top` на хосте, `dmesg \| grep apparmor`, `auditd` логи | Перейти на `SCMP_ACT_ALLOW` для нужных вызовов, перевести профиль в `enforce` после обучения |
| **Live migration падает с ошибкой доступа к образу** | Разные пути/метки SELinux на source и destination хосте | `virsh migrate --verbose`, `ausearch -m avc -ts recent` | Унифицировать пути к образам, использовать `sVirt` для автоматической маркировки, проверить shared storage |
| **eBPF/perf tracing не видит события гостя** | KVM установлен в `kvm_intel`/`kvm_amd` без `ept`/`npt`, или perf_event не включён в гостевом ядре | `kvm_stat`, `perf kvm --host`, `dmesg \| grep -i kvm` | Проверить `kvm-ok`, включить `perf_event_paranoid=1` или `-1` на хосте, добавить `perf` в образ |

## Лучшие практики

### Подготовка хоста

- **Tuned profile:** Используйте `virtual-host` на KVM-хостах. Profile `throughput-performance` подходит для batch-нагрузок без низкозадержочных требований.
- **Sysctl baseline:** Применяйте параметры из [KVM — host sysctl checklist](../../Linux/Virtualization/kvm/kvm_host_sysctl_checklist.md) как основу. Изменяйте инкрементально и тестируйте.
- **Аудит включён:** Включите `auditd` на хосте для фиксации событий libvirt, QEMU и AVC-нарушений SELinux. Конфигурируйте rotation логов.
- **Зависимости для scanning:** Убедитесь что `bc`, `jq`, `curl` присутствуют для scripts из практических сценариев.

### Изоляция инстансов

- **Immutable images:** Никогда не меняйте образ после подписания. Для изменений — новая версия с новым digest и SBOM.
- **Minimal drivers:** В образе только те драйверы, которые необходимы (сеть, диск, консоль). Отключите всё лишнее при сборке (sound, USB, DRM, legacy protocols).
- **Host-passthough + isolation:** Используйте `host-passthrough` CPU mode. Изолируйте `emulatorpin` на отдельные ядра, не пересекающиеся с vCPU.
- **Least Privilege для QEMU:** Запускайте QEMU от отдельного пользователя (например, `qemu`), без `root`. Не используйте `privileged` контейнеры для управления libvirt.
- **cgroups blkio:** Ограничивайте I/O на уровне libvirt (`<iotune>`), чтобы предотвратить noisy neighbor и обеспечить fairness.

### Сканирование и supply chain

- **Pipeline гейты:** В CI/CD блокируйте деплой при `CRITICAL` CVE, требующих сканирования с `trivy image --severity CRITICAL` и `grype --fail-on high`.
- **SBOM артефакт:** Храните SBOM вместе с образом в registry (attestation). Версионируйте SBOM.
- **Key rotation:** Ротация ключей `cosign` не реже 1 раза в 90 дней. Для keyless-подписания мониторьте срок действия сертификатов Fulcio (10–20 минут) — долгосрочная верификация требует Rekor SET.
- **VEX для false positives:** При ложных срабатываниях создавайте VEX-отчет со статусом `not_affected`, чтобы не блокировать pipeline.

### Мониторинг и алертинг

- **Базовые метрики:** `kvm_stat` exits/sec (особенно `kvm_exit` и `kvm_hv_apic`), `numastat` local vs remote, `ethtool -S` vhost packets/drops, `iostat` await.
- **Пороги алертов:** steal time > 5%, NUMA remote > 30%, vhost-net off, HugePages free = 0, QEMU TCG mode, AVC denials > 0 в час.
- **Audit log review:** Ежедневно проверяйте `ausearch -m avc -ts recent` и `journalctl -u libvirtd -u qemu` на предмет неожиданных отказов.
- **Сканирование по расписанию:** Запускайте `trivy image` и `grype` не реже 1 раза в неделю для golden images, при каждом изменении Library OS или зависимостей.

### Изменения в production

- **По одному параметру:** Вносите изменения в MAC/seccomp/сетевые политики по одному параметру за раз. Запускайте baseline audit до и после.
- **Complain → Enforce:** Новые AppArmor/SELinux профили сначала в `complain`/`permissive` режиме 24–48 часов, затем в `enforce`/`enforcing`.
- **Backout plan:** Перед применением seccomp-профиля или MAC-политики имейте rescue-режим (например, kernel параметр `apparmor=0` или `selinux=0` в GRUB).

## Граничные случаи

- **TCG mode (без KVM):** На хостах без VT-x/AMD-V QEMU работает в режиме TCG (emulation) с производительностью в 5–10 раз ниже. Все механизмы изоляции (AppArmor, SELinux, seccomp) работают, но surface атаки увеличивается из-за software TLB/shadow page tables. Никогда не используйте TCG в production для ненадежных workloads.
- **Live migration с разной топологией NUMA:** Не работает корректно. Проверяйте совместимость NUMA перед миграцией. Разная топология приводит к деградации производительности и потенциальным проблемам с NUMA-aware placement.
- **Multi-tenant хост:** На хостах с >10 юникернелов используйте отдельный `virt` пользователь для каждого tenant, динамические AppArmor профили через sVirt, и отдельные cgroups blkio для fairness.
- **Образы с firmware/BIOS:** Если юникернел загружается через SeaBIOS или OVMF, убедитесь что firmware не содержит уязвимостей (SeaBIOS CVE-2021-3868 и аналоги). Используйте только подписанные или вшитые firmware.
- **Снапшоты и белые списки:** Снапшоты qcow2 могут содержать данные из предыдущих запусков. Используйте `qemu-img create -b base.qcow2 -F qcow2 -f qcow2 overlay.qcow2` с read-only base, или `libvirt` `wipe_abort=on` для автоматической очистки.
- **eBPF/perf tracing на хосте:** Требует `perf_event_paranoid <= 1` и включённый `CONFIG_KVM_INTEL_PERF` или `CONFIG_KVM_AMD_PERF`. Без этого `perf kvm` не будет видеть гостевые события.

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md)
- [Преимущества и ограничения](./unikernel_advantages_disadvantages.md)
- [Оркестрация и управление](./orchestration_and_management.md)
- [Мониторинг и алертинг](./monitoring_and_alerting.md)
- [Сеть: продвинутые сценарии](./networking_advanced.md)

### Ссылки
- [Supply Chain Security — Container Image Supply Chain](../../Security/Supply_Chain_Security/container_image_supply_chain.md)
- [AppArmor — основы](../../Linux/Security/Mechanisms/AppArmor.md)
- [SELinux — основы](../../Linux/Security/Mechanisms/SELinux.md)
- [Seccomp — механизм изоляции](../../Linux/Security/Mechanisms/seccomp.md)
- [Cosign — подписание образов](https://docs.sigstore.dev/cosign/signing/overview/)
- [Trivy — сканер уязвимостей](https://aquasecurity.github.io/trivy/)
- [Syft — генерация SBOM](https://github.com/anchore/syft)
