# Vagrant и альтернативы: где что использовать

**Актуально для:** Vagrant 2.4.x

## Определения

**Vagrant** — инструмент для управления жизненным циклом локальных виртуальных машин через единый CLI и `Vagrantfile`. Идеален для воспроизводимых окружений разработки на одном хосте (VirtualBox, Libvirt/KVM, QEMU, Docker и др. — см. [Vagrant Providers](./vagrant_providers.md)).

**Docker** — рантайм контейнеров: изоляция на уровне процессов/ядра хоста без полноценной ОС, образы из слоёв, мгновенный старт. Внутри Vagrant может выступать провайдером («контейнер как машина») — см. [Vagrant Providers: Docker](./vagrant_providers.md).

**Terraform / OpenTofu** — инструмент инфраструктуры как кода (IaC) для **создания и управления инфраструктурой** (ВМ, сети, кластеры) на удалённых платформах: облака, KVM, vSphere и т.д. Декларативный план/apply + state-файл. Базовые концепции — в [IaC Overview](../Concepts/iac_overview.md).

**Minikube** — инструмент запуска одноколоночного кластера Kubernetes локально (драйверы: Docker, KVM, VirtualBox, QEMU). Для разработки с настоящим API Kubernetes.

**k3s** — легковесный дистрибутив Kubernetes (single binary ~50 МБ) с встроенным containerd, Flannel CNI и local-path CSI. CNCF-сертифицированный, подходит для edge/IoT и локальной разработки. См. [K3s Dev Environment](../Kubernetes/Installation/k3s_dev_environment/k3s_architecture.md).

**kind (Kubernetes IN Docker)** — запуск полноценных узлов Kubernetes как Docker-контейнеров с systemd и containerd. Использует kubeadm для бутстрейпа. Идеален для тестирования Kubernetes и CI/CD. См. [kind: концепции](../Kubernetes/Installation/kind/kind_concepts.md).

**Podman** — демонлесс контейнерный рантайм с rootless-first архитектурой. Полный OCI-совместимый интерфейс с Docker. См. [Podman vs Docker](../Podman/podman_vs_docker.md).

**Multipass** — управлятор легковесных Ubuntu VM от Canonical. Использует облачные образы и cloud-init для настройки. Поддерживает нативные гипервизоры (QEMU на Linux, Apple Virtualization framework на macOS, Hyper-V на Windows). Лицензия GPL-3.0.

**Nova** — современная замена Vagrant для тестирования распределённых систем. Single binary, rootless by default, поддерживает OCI-образы и cloud-init. Использует нативные гипервизоры (Apple Virtualization.framework, QEMU/KVM).

**migrant** — лёгкий Vagrant-подобный менеджер ВМ для Linux на базе libvirt + QEMU/KVM. Конфигурация через `Migrantfile` (Bash) + cloud-init (YAML).

Эти инструменты не конкуренты «в одной нише»: это разные слои. Сравнение Podman и Docker (близкие конкуренты) — в [Podman vs Docker](../Podman/podman_vs_docker.md). Обзор выбора стека DevOps — в [DevOps Stack Selection](../Concepts/devops_stack_selection.md).

## Предварительные требования

Для корректного выбора между Vagrant и альтернативами в контексте devops, SRE и системного администрирования необходимо понимание следующих компетенций и ограничений:

- **Системное администрирование:** способность управлять ВМ (загрузка, сеть, firewall, systemd), понимание разницы между полноценной ОС и контейнером, знание образцов cloud-init.
- **Контейнеризация:** понимание OCI-образов, containerd/runc, различий между rootful/rootless режимами, ограничений контейнеров по изоляции ядра.
- **IaC-практики:** знание декларативных подходов (Terraform/OpenTofu), принципов состояния (state), идемпотентности и drift detection.
- **Kubernetes:** понимание архитектуры (control-plane, kubelet, CNI, CSI), разницы между «реальным» и «симулируемым» k8s (kind/minikube vs k3s/kubeadm).
- **CI/CD:** умение запускать ephemeral окружения в пайплайнах, знание ограничений ресурсов и времени запуска.
- **Безопасность:** понимание attack surface (полная ВМ vs контейнер), управление SSH-ключами, принцип минимальных привилегий.

## Базовые концепции

### Слои автоматизации (не пересечение)

| Слой | Вопрос, который решает | Инструменты |
| :--- | :--- | :--- |
| Окружение разработчика | «Дай мне изолированную ВМ с готовым софтом» | **Vagrant**, Multipass, Nova, migrant, Docker compose local |
| Изоляция процессов/приложений | «Упакуй приложение в лёгкий образ» | **Docker**, Podman |
| Управление инфраструктурой/облаком | «Создай/измени/удали прод-ресурсы воспроизводимо» | **Terraform**/OpenTofu, Ansible |
| Кластер Kubernetes локально | «Дай мне настоящий k8s API для разработки» | **k3s**, **kind**, Minikube |

### Ключевые отличия состояния и жизненного цикла

- **Vagrant** управляет полной виртуальной машиной: своя ОС, гипервизор, состояние в `.vagrant/`, команды `up / halt / suspend / destroy`. Модель «рабочая станция».
- **Docker** делит ядро хоста, контейнеры эфемерны, воспроизводимость — в `Dockerfile` и образах. Быстрый, но не изолирует от ядра (для тестов ОС с systemd и т.п. не подходит без приёмов).
- **Terraform** описывает **целевую** инфраструктуру (обычно прод/стейджинг) и поддерживает её состояние; не запускает процессы и не управляет приложениями на ВМ (для этого — Ansible или cloud-init).
- **Minikube** / **kind** / **k3s** поднимают полноценный control-plane; драйвером может использовать Docker, гипервизор или работать в контейнере.

### Место Vagrant в продакшене

Vagrant — инструмент **локальной разработки и тестирования**, а не продакшена. Ограничения:

- **Один хост/один пользователь**: мульти-машины живут в пределах одного `Vagrantfile` и одного гипервизора; нет планировщика и фейловера.
- **Состояние в `.vagrant/`**: локальные метаданные, не предназначены для командной эксплуатации; для HA/мониторинга/оркестрации продакшена нужны другие инструменты (Kubernetes, cloud, virt-оркестраторы).
- **Push/деплей** (Vagrant Push, Atlas) давно не развиваются; депллой приложений делается CI/CD, а не Vagrant.

Именно поэтому на собеседованиях и в продакшене важно не путать: Vagrant закрывает задачу «воспроизводимое дев-окружение», а не «обслуживание прод-инфраструктуры».

## Практические сценарии

### Сценарий 1: Таблица выбора по критериям

| Критерий | Vagrant | Docker | Terraform/OpenTofu | Minikube / kind / k3s |
| :--- | :--- | :--- | :--- | :--- |
| Изоляция | Полная ВМ | Контейнер (общее ядро) | Ресурсы облака/гипервизора | Одноузловой k8s (контейнер/ВМ) |
| Bootstrap «с нуля» | `vagrant up` | `docker run` | `terraform apply` | `curl -sfL https://get.k3s.io \| sh -` / `kind create cluster` |
| Мульти-компонентная сеть | + | + (compose/networks) | + (VPC, security groups) | k8s service/ingress |
| Тест «другая ОС» (Ubuntu/Debian/RHEL) | + | − (ядро хоста) | + (образы облака) | − |
| Воспроизводимость окружения | `Vagrantfile` | `Dockerfile`/compose | `.tf` + state | config start / `k3s.yaml` |
| Prod-как-код | Нет | Частично (runtime) | Да | Частично (манифесты k8s) |
| CI-friendly | Да (libvirt/docker provider) | Да | Да | Да (короткое время запуска) |
| Когда выбирать | Локальная разработка, тесты на реальной ОС, обучение/интервью | Микросервисы, быстрое прототипирование | Прод-инфраструктура как код | Разработка против k8s API |

### Сценарий 2: Vagrant + Docker вместе

Vagrant-провайдер Docker позволяет описывать контейнеры как «машины» и использовать общий CI/workflow Vagrant:

```ruby
Vagrant.configure("2") do |config|
  config.vm.provider "docker" do |d|
    d.image = "ubuntu:24.04"
    d.has_ssh = true
    d.remains_running = true
  end
end
```

Сценарий, когда нужен именно Vagrant, а не Docker: требуется полная ОС (systemd, свои ядерные модули, сети libvirt), задача «поднять кластер как у прода» на своей машине.

### Сценарий 3: Vagrant локально → Terraform в стейджинге

Типичный паттерн: разработчик гонит то же приложение на Vagrant-ВМ, а стейджинг/прод создаётся Terraform + Ansible. Один и тот же Ansible-плейбук провижинга работает у обоих мест, что исключает дрейф «на моей машине работает».

```bash
# Локально (Vagrant, box bento/ubuntu-24.04 + ansible-провижинер)
vagrant up --provider=libvirt

# Стейджинг (Terraform: module "vm" { ... } + remote-exec/Ansible)
terraform init && terraform apply -var env=staging
```

### Сценарий 4: Быстрый bootstrap для сравнения

```bash
# Vagrant: ВМ с Ubuntu за минуту
vagrant init bento/ubuntu-24.04 && vagrant up

# Docker: контейнер Ubuntu без полноценной ОС
docker run -it --rm ubuntu:24.04 bash

# Multipass: Ubuntu VM за ~60 секунд (cloud-init)
multipass launch lts --name dev-vm

# Minikube: кластер k8s локально
minikube start --driver=docker && kubectl get nodes

# k3s: лёгкий k8s (single binary)
curl -sfL https://get.k3s.io | sh -

# kind: k8s в Docker-контейнерах
kind create cluster && kubectl get nodes

# Terraform: локальный libvirt-провайдер как мини-Terraform
terraform init && terraform apply   # создаёт qcow2-ВМ через libvirt provider
```

### Сценарий 5: Анализ «интервью vs продакшен»

- **Интервью (devops/sre/sysadmin):** ожидают, что вы понимаете разницу слоёв и умеете выбрать инструмент: «Vagrant для воспроизводимого дев-окружения», «Docker для упаковки приложений», «Terraform для IaC инфраструктуры», «k3s/kind/Minikube для локального k8s».

  **Типичные вопросы на интервью:**
  - *Почему Vagrant не используется в продакшене?* — Потому что Vagrant управляет ВМ на одном хосте без HA, scheduler и failver. Не масштабируется для продакшена.
  - *В чём разница между Docker и Vagrant?* — Docker изолирует процессы на уровне ядра (общее ядро хоста), Vagrant создаёт полноценную ВМ с отдельной ОС.
  - *Когда выбрать k3s, а когда kind?* — k3s для production-паритета (real CNI/CSI, real upgrade flow); kind для тестирования самого Kubernetes и CI/CD (fast startup, multi-node HA).
  - *Можно ли использовать Vagrant в CI/CD?* — Да, через libvirt или docker-провайдер, но с оговоркой: требует гипервизор на CI-агенте и больше ресурсов, чем контейнеры.

- **Прод:** применяют Terraform/Ansible/Kubernetes. Если у вас спрашивают «где в проде Vagrant» — честный ответ: как правило, нигде, кроме CI-джобов и машины разработчика.

### Сценарий 6: Vagrant vs Multipass — выбор для Ubuntu-окружений

| Критерий | Vagrant | Multipass |
| :--- | :--- | :--- |
| Гостевая ОС | Любая (Ubuntu, Debian, RHEL, CentOS и др.) | Только Ubuntu |
| Конфигурация | Vagrantfile (Ruby) | cloud-init YAML |
| Гипервизор | VirtualBox, Libvirt, VMware, QEMU, Hyper-V | Нативный (QEMU/KVM, HVF, Hyper-V) |
| Скорость запуска | 1-3 минуты | ~60 секунд |
| Размер образа | 0.5-4 ГБ (box) | ~300 МБ (cloud image) |
| Лицензия | BSL 1.1 (временно), переход на MPL 2.0 через 4 года | GPL-3.0 |

**Когда Multipass предпочтительнее:** нужна только Ubuntu-окружение, важна скорость запуска и минимальный overhead. **Когда Vagrant предпочтительнее:** нужна не-Ubuntu ОС, сложная сеть (multi-machine), провижининг через Ansible/Puppet, или требуется воспроизводимость через `Vagrantfile`.

### Сценарий 7: Nova и migrant — новые альтернативы

**Nova** (tripleclabs/nova) — современная замена Vagrant для тестирования распределённых систем. Поддерживает OCI-образы из container registries, cloud-init провижининг, multi-node кластеры, сетевую хаос-инженерию и интерактивный TUI. Single binary, rootless by default, использует нативные гипервизоры (Apple Virtualization.framework на macOS, QEMU/KVM на Linux).

**migrant** (pigmonkey/migrant) — лёгкий Vagrant-подобный менеджер ВМ для Linux на базе libvirt + QEMU/KVM. Конфигурация через `Migrantfile` (Bash) + `cloud-init.yml` (YAML). Быстрее Vagrant за счёт qcow2 backing files (copy-on-write) и использует `virtiofs` вместо `vboxsf` для безопасного доступа к файлам.

## Устранение неполадок

### Типичные ошибки выбора инструмента

| Ошибка | Почему это ошибка | Правильный выбор |
| :--- | :--- | :--- |
| Использование Vagrant для продакшена | Нет HA, scheduler, failver; не масштабируется | Terraform + Ansible для инфраструктуры; Kubernetes для оркестрации |
| Использование Docker вместо Vagrant для тестов ОС | Контейнеры делят ядро хоста; нельзя тестировать systemd, kernel modules | Vagrant (полная ВМ) или k3s в VM |
| Использование minikube для production-паритета | Симуляция: kindnet вместо real CNI, hostPath вместо real CSI | k3s или kubeadm на VM |
| Использование Vagrant вместо Docker для микросервисов | Тяжеловесные ВМ вместо лёгких контейнеров; медленный старт | Docker/Podman + docker-compose |
| Использование `latest`-тегов образов | Непрогнозируемые обновления; drift в окружениях | Pin версии box/image |
| Смешивание HashiCorp BSL и MPL лицензий | BSL 1.1 ограничивает коммерческое использование | OpenTofu вместо Terraform в коммерческих проектах |

### Диагностика выбора инструмента

Перед выбором инструмента задайте себе вопросы:

```bash
# 1. Нужна ли полная ОС или достаточно контейнера?
#    → Полная ОС (systemd, kernel modules): Vagrant / Multipass / Nova
#    → Только процессы: Docker / Podman

# 2. Нужен ли реальный Kubernetes API или достаточно "kubectl works"?
#    → Production-паритет: k3s на VM
#    → Тестирование k8s: kind (fast, multi-node)
#    → Быстрая итерация: k3d (k3s в Docker)

# 3. Где разворачивается инфраструктура?
#    → Локально на ноутбуке: Vagrant / Multipass / kind / k3s
#    → Удалённо (production/staging): Terraform + Ansible

# 4. Какая ОС нужна?
#    → Только Ubuntu: Multipass (оптимально)
#    → Any OS: Vagrant (универсально)
```

## Рекомендации и лучшие практики

1. **Не смешивайте слои:** Vagrant/Docker/k3s/kind/minikube решают разные задачи. Vagrant — полная ВМ для dev-окружения; Docker/Podman — контейнеры для приложений; Terraform — инфраструктура как код; k3s/kind/minikube — локальный Kubernetes. Не пытайтесь «заменить Vagrant Docker», если нужна полная ОС.

2. **Pin версии образов:** всегда фиксируйте версию box (`config.vm.box_version`), Docker-образа (`ubuntu:24.04`) и k8s-образа (`kindest/node:v1.37.0`). Использование `latest` приводит к непредсказуемому поведению.

3. **Единый провижининг:** используйте один и тот же Ansible-плейбук для Vagrant (локально) и Terraform+Ansible (стейджинг/прод). Это исключает дрейф конфигураций.

4. **CI/CD-дружелюбность:** для пайплайнов предпочтительнее libvirt/docker-провайдеры Vagrant (headless, без GUI) или контейнеры (Docker/Podman). Настраивайте `VAGRANT_NO_TTY=1`, `VAGRANT_BOX_UPDATE_CHECK=0` для воспроизводимых билдов.

5. **Удаляйте ВМ после использования:** `vagrant destroy -f` освобождает ресурсы. Не оставляйте running-ВМ на ноутбуке — это расходует RAM и диск.

6. **Верификация образов:** при добавлении box из внешних источников всегда указывайте `--checksum sha256`. Для Docker/Podman используйте digest-ссылки (`image@sha256:...`) вместо тегов.

7. **Лицензионная осознанность:** Vagrant 2.4.3+ использует BSL 1.1 ( HashiCorp → IBM). Для open-source проектов рассмотрите Multipass (GPL-3.0), Nova или migrant. OpenTofu (MPL 2.0) — open-source альтернатива Terraform.

8. **Слои как в проде:** если production использует k3s или kubeadm на VM — используйте k3s на VM для dev-паритета. kind/minikube подходят только для unit-тестов k8s-манифестов.

## Границы и крайние случаи

- **Vagrant в эпху контейнеров:** Vagrant теряет долю аудитории после Docker/Podman и k3s. Однако остаётся незаменимым, когда нужна полная ОС: тесты systemd-сервисов, kernel modules, network namespaces, RHEL-специфичное поведение.
- **HCP Vagrant deprecation:** HashiCorp Cloud Platform Vagrant registry устаревает. Новые box больше не могут быть созданы после 1 октября 2026 года; существующие работают до 31 декабря 2026 года. Используйте публичные источники (bento, generic, debian) или внутренние зеркала через `box_url`.
- **k3s в Docker (k3d):** удобен для скорости, но унаследует ограничения kind — нет real CNI/CSI, container-as-node. Не подходит для тестирования network policies.
- **Multipass — Ubuntu-only:** если нужна RHEL/CentOS/AlmaLinux, Multipass не подходит. Vagrant или k3s на VM — вариант.
- **Nova и migrant — молодые проекты:** ограниченная документация, малая комьюнити. Подходят для experimental use cases, но не для production-стандартов.

## Дополнительная информация

### Когда Vagrant всё-таки бывает в продакшене

Vagrant-ВМ допустимы в продакшене в ограниченных ролях:

- выступления для **изолированных задач в CI/CD** (cryptographic провижининг заменяет облачный раннер);
- **возрастающие/legacy-среды** без гипервизорной автоматизации (один хост, один сервис);
- **teenv/мастеринг** интерактивных сервисов (demo, испытания) без требований HA.

В остальном для боевой инфраструктуры используйте гипервизорные платформы/Kubernetes/облако с Terraform+Ansible.

### Связанные концепции

- [IaC Overview](../Concepts/iac_overview.md) — декларативная инфраструктура как код.
- [DevOps Stack Selection](../Concepts/devops_stack_selection.md) — выбор стека инструментов.
- [Podman vs Docker](../Podman/podman_vs_docker.md) — сравнение двух контейнерных рантаймов.
- [Vagrant Providers](./vagrant_providers.md) — провайдер Docker внутри Vagrant, гипервизоры.
- [kind: концепции](../Kubernetes/Installation/kind/kind_concepts.md) — Kubernetes IN Docker, архитектура и ограничения.
- [K3s Dev Environment](../Kubernetes/Installation/k3s_dev_environment/k3s_architecture.md) — лёгкий Kubernetes для dev/local.

### См. также

- [Vagrant Basic Workflow](./vagrant_basic_workflow.md) — жизненный цикл `vagrant up`.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машины, триггеры, продвинутые сценарии.
- [Vagrant Provisioning](./vagrant_provisioning.md) — провижининг (Ansible, Docker, shell).
- [Vagrant Providers](./vagrant_providers.md) — провайдеры и образы (boxes), HCP Vagrant deprecation.
- [Vagrant Installation](./vagrant_installation.md) — установка, версии, лицензия BSL 1.1.