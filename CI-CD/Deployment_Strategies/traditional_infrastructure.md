# Развертывание в традиционной инфраструктуре (Bare Metal / VM)

## Определения

- **Традиционная инфраструктура** — серверные ресурсы, представленные физическим оборудованием (Bare Metal) или виртуальными машинами (VM), управление которыми осуществляется напрямую через ОС, а не через высокоуровневые API оркестраторов типа Kubernetes.
- **Мутабельная инфраструктура (Mutable Infrastructure)** — подход, при котором изменения вносятся непосредственно в работающие серверы (например, через SSH или конфигурационное управление). Серверы живут долго и «накапливают» состояние.
- **Иммутабельная инфраструктура (Immutable Infrastructure)** — подход, при котором серверы не обновляются «на месте». Для внесения изменений создается новый образ (Golden Image), развертываются новые серверы, а старые уничтожаются.
- **Golden Image (Золотой образ)** — предварительно настроенный и протестированный образ диска или виртуальной машины, содержащий ОС, системные зависимости, агенты мониторинга и само приложение, готовый к немедленному запуску.
- **Конфигурационное управление (CM)** — инструменты автоматизации настройки серверов (Ansible, Chef, Puppet, SaltStack), обеспечивающие декларативное описание целевого состояния.
- **Внутренняя платформа разработчика (Internal Developer Platform, IDP)** — набор инструментов и сервисов, предоставляющий разработчикам «Золотые пути» (Golden Paths) для самообслуживания инфраструктурой, включая автоматизированный заказ VM и Bare Metal.
- **SBOM (Software Bill of Materials)** — структурированный перечень всех компонентов, библиотек и зависимостей, включенных в образ или артефакт, необходимый для обеспечения безопасности цепочки поставок (Supply Chain Security).
- **Micro-VM** — легковесные виртуальные машины (например, Firecracker), обеспечивающие изоляцию аппаратного уровня с быстротой запуска контейнеров.

---

## Основные концепции

### Эволюция подходов: От ручной автоматизации к Platform Engineering

В 2026 году развертывание в традиционной среде перестало быть «ручным» процессом и интегрировалось в общую экосистему Platform Engineering. Основной фокус сместился на автономность, безопасность и экономическую эффективность (FinOps).

#### Паттерны деплоя в традиционной среде

| Паттерн | Описание | Инструменты | Подход |
| :--- | :--- | :--- | :--- |
| **Agentless Push (SSH)** | CI-раннер инициирует соединение и выполняет плейбуки. Требует JIT-доступа (Just-in-Time). | Ansible, Fabric, SSH. | Мутабельный |
| **Agent-based Pull (GitOps)** | Агент на хосте периодически синхронизирует состояние с Git-репозиторием. | Ansible-pull, Salt-minion. | Мутабельный |
| **Image-based Deployment** | Полная замена инстансов на основе обновленных Golden Images. Минимизирует дрифт. | Packer, Terraform, Cloud-init. | Иммутабельный |
| **Hybrid Orchestration** | Запуск гетерогенных нагрузок (бинарники + контейнеры) через единый Control Plane. | HashiCorp Nomad, Proxmox. | Гибридный |
| **Bare Metal Cloud** | Управление физическими серверами как облачными ресурсами через API (PXE/ZTP). | Equinix Metal, Ironic, MAAS. | Иммутабельный |

### Жизненный цикл деплоя на 2026 год

1.  **Zero-Touch Provisioning (ZTP):** Автоматическое обнаружение и базовая настройка нового «железа» или VM при включении.
2.  **Secure-by-Design Boot:** Проверка целостности прошивки и загрузчика (Secure Boot, TPM 2.0).
3.  **Policy-as-Code Validation:** Проверка конфигурации на соответствие стандартам безопасности (OPA, `ansible-lint`) до начала деплоя.
4.  **Artifact Deployment & SBOM Signing:** Доставка артефактов с проверкой криптографических подписей.
5.  **Runtime Attestation:** Постоянный мониторинг целостности системы и обнаружение дрифта в реальном времени.
6.  **Observability-driven Verification:** Smoke-тесты на основе eBPF-метрик для проверки сетевой связности и производительности I/O.
7.  **FinOps & Green Tracking:** Сбор данных о энергопотреблении и стоимости эксплуатации ресурсов после деплоя.

---

## Практические сценарии

### Сценарий 1: Продвинутый CI/CD через Ansible (Push-модель)

Используется для систем, где полная замена VM невозможна или нецелесообразна (например, тяжелые БД).

**Предварительные требования:**
- Ansible 2.15+ на раннере.
- Доступ по SSH через JIT-шлюз (например, Teleport или HashiCorp Boundary).
- Хранилище секретов HashiCorp Vault.

**Рабочий процесс (GitLab CI):**
```yaml
deploy_app:
  stage: deploy
  script:
    - export VAULT_TOKEN=$(vault auth move ...)
    - ansible-lint playbooks/deploy.yml
    - ansible-playbook -i inventory/prod.ini playbooks/deploy.yml \
      --extra-vars "app_version=${CI_COMMIT_TAG}"
```

**Плейбук (playbooks/deploy.yml):**
```yaml
- hosts: app_servers
  become: true
  vars:
    app_path: "/opt/apps/my-service"
    db_password: "{{ lookup('community.hashi_vault.vault_kv', 'secret/data/prod/db:password') }}"

  tasks:
    - name: "Verification: Check free space"
      assert:
        that: "ansible_mounts[0].size_available > 500000000"
        fail_msg: "Insufficient disk space for deployment"

    - name: "Download and Verify Artifact"
      get_url:
        url: "https://artifactory.local/my-app-{{ app_version }}.tar.gz"
        dest: "/tmp/my-app.tar.gz"
        checksum: "sha256:{{ lookup('url', 'https://artifactory.local/my-app.sha256') }}"

    - name: "Extract to versioned directory"
      unarchive:
        src: "/tmp/my-app.tar.gz"
        dest: "{{ app_path }}-{{ app_version }}"
        remote_src: yes

    - name: "Update Symbolic Link (Atomic switch)"
      file:
        src: "{{ app_path }}-{{ app_version }}"
        dest: "{{ app_path }}/current"
        state: link
      notify: "Restart and Validate Service"

  handlers:
    - name: "Restart and Validate Service"
      systemd:
        name: my-service
        state: restarted
        enabled: true
      register: service_status
      failed_when: service_status.state != 'started'
```

### Сценарий 2: Immutable Infrastructure (Packer + Terraform + Cloud-init)

Золотой стандарт для масштабируемых веб-приложений и stateless-сервисов.

**Этапы:**
1.  **Bake (Сборка):** Packer создает образ, устанавливая зависимости и генерируя SBOM.
    ```hcl
    # packer/template.pkr.hcl
    build {
      sources = ["source.vsphere.ubuntu"]
      provisioner "ansible" {
        playbook_file = "./setup.yml"
      }
      post-processor "manifest" {
        output = "manifest.json"
      }
    }
    ```
2.  **Verify:** Сканирование образа на уязвимости (Trivy/Clair).
3.  **Deploy (Развертывание):** Terraform обновляет шаблон в Auto Scaling Group или гипервизоре.
    ```hcl
    resource "vsphere_virtual_machine" "app" {
      name             = "app-${var.app_version}"
      clone {
        template_uuid = data.vsphere_virtual_machine.template.id
      }
      extra_config = {
        "guestinfo.userdata" = base64encode(data.template_file.cloud_init.rendered)
      }
    }
    ```

**Validation:** Cloud-init выполняет финальную настройку (регистрация в Consul/DNS) и сигнализирует о готовности через эндпоинт мониторинга.

### Сценарий 3: GitOps для VM через Ansible-pull

Подход, исключающий необходимость открытого SSH-порта на серверах.

**Механизм:**
- На каждом сервере настроен `cron` или `systemd-timer`, запускающий `ansible-pull`.
- Агент скачивает изменения из Git и применяет их локально.

```bash
# Пример команды запуска
ansible-pull -U https://git.company.com/infra/config.git \
             -i localhost, \
             local.yml
```

---

## Особенности и ограничения

- **Дрифт конфигурации (Configuration Drift):** В мутабельной среде серверы неизбежно «стареют». Решение — переход на Immutable или ежедневный принудительный прогон Ansible в режиме `--diff`.
- **Latency & Storage:** При деплое на Bare Metal критически важна настройка **NVMe-over-Fabrics (NVMe-oF)** и тюнинг сетевого стека (DPDK/SR-IOV) для высоконагруженных приложений.
- **Clock Drift:** Виртуальные машины подвержены «уплыванию» времени. Необходимо использовать `chrony` с PTP-источниками для синхронизации с точностью до микросекунд (важно для распределенных БД).
- **Скорость отката:** В традиционной среде откат часто требует переустановки ОС или восстановления из LVM-снимков.

---

## Лучшие практики и эксплуатация

### Безопасность (Zero Trust & DevSecOps)
- **JIT Access (Just-in-Time):** Полный отказ от постоянно открытых SSH-портов. Доступ предоставляется временно через IAP-прокси или системы типа **Teleport**.
- **Runtime Attestation:** Использование **Keylime** или **Spiffe/Spire** для проверки целостности ноды и выдачи динамических сертификатов только доверенным хостам.
- **Micro-segmentation:** Настройка локальных файрволов (nftables/firewalld) через IaC для ограничения трафика между сервисами внутри сегмента Bare Metal.

### Мониторинг и Observability
- **Node Exporter & eBPF:** Сбор не только базовых метрик (CPU/RAM), но и детальной статистики по системным вызовам и сетевым задержкам через eBPF-экспортеры.
- **Log Aggregation:** Использование **Vector** или **Fluent-bit** для сбора логов `journald` и передачи их в централизованное хранилище (Loki/Elastic).

### FinOps и Green Ops
- **Экономическая эффективность:** Автоматическое выключение тестовых VM в нерабочее время и использование Spot-инстансов для пакетной обработки данных.
- **Sustainability:** Мониторинг метрик энергопотребления через **Scaphandre** или IPMI для расчета углеродного следа (Carbon Footprint) инфраструктуры.

---

## Устранение неполадок (Troubleshooting)

### Обнаружение дрифта (Drift Detection)
- **Сценарий:** Конфигурация на сервере отличается от описанной в Git.
- **Решение:** Запуск Ansible в режиме проверки (`--check --diff`). Использование **Terraform Drift Detection** в CI/CD для выявления изменений, внесенных вручную через консоль гипервизора.

### Проблемы с производительностью I/O
- **Симптомы:** Высокий `iowait`, задержки в работе БД.
- **Диагностика:** 
  - `iostat -xz 1` — анализ утилизации дисков.
  - `nvme smart-log /dev/nvme0` — проверка состояния NVMe-накопителей.
- **Тюнинг:** Настройка планировщика I/O (`deadline` или `none` для SSD) и параметров `dirty_ratio` в `sysctl`.

### Сетевые задержки и потери пакетов
- **Диагностика:** 
  - `mtr` — поиск узких мест в маршруте.
  - `ethtool -S eth0` — поиск ошибок на физическом уровне (CRC errors, drops).
- **Решение:** Проверка соответствия MTU на всех участках сети, тюнинг очередей сетевой карты (`ethtool -G`).

### Рассинхронизация времени (Clock Drift)
- **Сценарий:** Ошибки в работе распределенных систем (Kafka, Cassandra).
- **Решение:** Переход на `chrony` с указанием нескольких PTP или stratum-1 источников. Проверка статуса через `chronyc tracking`.

---

## Дополнительная информация

### См. также
- **[Стратегии развертывания (Сравнение)](./comparison.md)** — Blue/Green, Canary и их применимость.
- **[Nomad: Практические сценарии](../../Nomad/practical_scenarios.md)** — запуск гетерогенных нагрузок.
- **[Ansible: Лучшие практики](../../Ansible/ansible_security_best_practices.md)** — управление секретами и ролями.
- **[LVM — Снимки](../../Linux/FileSystems/LVM/snapshots.md)** — механизмы быстрого отката на уровне ФС.
- **[Health Checks и Rollback](./deployment_health_checks_and_rollback.md)** — методы автоматической проверки после деплоя.

