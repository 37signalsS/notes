# Vagrant и альтернативы: где что использовать

## Определения

**Vagrant** — инструмент для управления жизненным циклом локальных виртуальных машин через единый CLI и `Vagrantfile`. Идеален для воспроизводимых окружений разработки на одном хосте (VirtualBox, Libvirt/KVM, QEMU, Docker и др. — см. [Vagrant Providers](./vagrant_providers.md)).

**Docker** — рантайм контейнеров: изоляция на уровне процессов/ядра хоста без полноценной ОС, образы из слоёв, мгновенный старт. Внутри Vagrant может выступать провайдером («контейнер как машина») — см. [Vagrant Providers: Docker](./vagrant_providers.md).

**Terraform / OpenTofu** — инструмент инфраструктуры как кода (IaC) для **создания и управления инфраструктурой** (ВМ, сети, кластеры) на удалённых платформах: облака, KVM, vSphere и т.д. Декларативный план/apply + state-файл. Базовые концепции — в [IaC Overview](../Concepts/iac_overview.md).

**Minikube** — инструмент запуска одноколоночного кластера Kubernetes локально (драйверы: Docker, KVM, VirtualBox, QEMU). Для разработки с настоящим API Kubernetes.

Эти инструменты не конкуренты «в одной нише»: это разные слои. Сравнение Podman и Docker (близкие конкуренты) — в [Podman vs Docker](../Podman/podman_vs_docker.md). Обзор выбора стека DevOps — в [DevOps Stack Selection](../Concepts/devops_stack_selection.md).

## Базовые концепции

### Слои автоматизации (не пересечение)

| Слой | Вопрос, который решает | Инструменты |
| :--- | :--- | :--- |
| Окружение разработчика | «Дай мне изолированную ВМ с готовым софтом» | **Vagrant**, Multivagant, Docker compose local |
| Изоляция процессов/приложений | «Упакуй приложение в лёгкий образ» | **Docker**, Podman |
| Управление инфраструктурой/облаком | «Создай/измени/удали прод-ресурсы воспроизводимо» | **Тerraform**/OpenTofu, Ansible |
| Кластер Kubernetes локально | «Дай мне настоящий k8s API для разработки» | **Minikube**, k3s, kind, K8s |

### Ключевые отличия состояния и жизненного цикла

- **Vagrant** управляет полной виртуальной машиной: своя ОС, гипервизор, состояние в `.vagrant/`, команды `up / halt / suspend / destroy`. Модель «рабочая станция».
- **Docker** делит ядро хоста, контейнеры эфемерны, воспроизводимость — в `Dockerfile` и образах. Быстрый, но не изолирует от ядра (для тестов ОС с systemd и т.п. не подходит без приёмов).
- **Terraform** описывает **целевую** инфраструктуру (обычно прод/стейджинг) и поддерживает её состояние; не запускает процессы и не управляет приложениями на ВМ (для этого — Ansible или cloud-init).
- **Minikube** поднимает полноценный control-plane; драйвером может использовать Docker или гипервизор.

### Место Vagrant в продакшене

Vagrant — инструмент **локальной разработки и тестирования**, а не продакшена. Ограничения:

- **Один хост/один пользователь**: мульти-машины живут в пределах одного `Vagrantfile` и одного гипервизора; нет планировщика и фейловера.
- **Состояние в `.vagrant/`**: локальные метаданные, не предназначены для командной эксплуатации; для HA/мониторинга/оркестрации продакшена нужны другие инструменты (Kubernetes, cloud, virt-оркестраторы).
- **Push/деплой** (Vagrant Push, Atlas) давно не развиваются; деплой приложений делается CI/CD, а не Vagrant.

Именно поэтому на собеседованиях и в продакшене важно не путать: Vagrant закрывает задачу «воспроизводимое дев-окружение», а не «обслуживание прод-инфраструктуры».

## Практические сценарии

### Сценарий 1: Таблица выбора по критериям

| Критерий | Vagrant | Docker | Terraform/OpenTofu | Minikube |
| :--- | :--- | :--- | :--- | :--- |
| Изоляция | Полная ВМ | Контейнер (общее ядро) | Ресурсы облака/гипервизора | Одноузловой k8s |
| Boostrap «с нуля» | `vagrant up` | `docker run` | `terraform apply` | `minikube start` |
| Мульти-компонентная сеть | + | + (compose/networks) | + (VPC, security groups) | k8s service/ingress |
| Тест «другая ОС» (Ubuntu/Debian/RHEL) | + | − (ядро хоста) | + (образы облака) | − |
| Воспроизводимость окружения | `Vagrantfile` | `Dockerfile`/compose | `.tf` + state | config start |
| Прод-как-код | Нет | Частично (runtime) | Да | Нет |
| CI-friendly | Да (libvirt/docker provider) | Да | Да | Да |
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

# Стейдинг (Terraform: module "vm" { ... } + remote-exec/Ansible)
terraform init && terraform apply -var env=staging
```

### Сценарий 4: Быстрый bootstrap для сравнения

```bash
# Vagrant: ВМ с Ubuntu за минуту
vagrant init bento/ubuntu-24.04 && vagrant up

# Docker: контейнер Ubuntu без полноценной ОС
docker run -it --rm ubuntu:24.04 bash

# Minikube: кластер k8s локально
minikube start --driver=docker && kubectl get nodes

# Terraform: локальный libvirt-провайдер как мини-Terraform
terraform init && terraform apply   # создаёт qcow2-ВМ через libvirt provider
```

### Сценарий 5: Анализ «интервью vs продакшен»

- **Интервью (devops/sre/sysadmin):** ожидают, что вы понимаете разницу слоёв и умеете выбрать инструмент: «Vagrant для воспроизводимого дев-окружения», «Docker для упаковки приложений», «Terraform для IaC инфраструктуры», «Minikube/k3s для локального k8s».
- **Прод:** применяют Terraform/Ansible/Kubernetes. Если у вас спрашивают «где в проде Vagrant» — честный ответ: как правило, нигде, кроме CI-джобов и машины разработчика.

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

### См. также

- [Vagrant Basic Workflow](./vagrant_basic_workflow.md) — жизненный цикл `vagrant up`.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машины, триггеры, продвинутые сценарии.
- [Vagrant Provisioning](./vagrant_provisioning.md) — провижининг (Ansible, Docker, shell).