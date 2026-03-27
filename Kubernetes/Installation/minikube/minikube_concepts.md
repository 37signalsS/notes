# Minikube: Определения и концепции

## Определения

**Minikube** — инструмент для запуска локального однонодового кластера Kubernetes на рабочей машине. Предназначен для разработки, тестирования и обучения. Minikube разворачивает полноценный, но упрощённый кластер Kubernetes внутри виртуальной машины, Docker-контейнера или на bare metal.

**kubeconfig** — YAML-файл (`~/.kube/config`), содержащий информацию о кластерах, пользователях и контекстах для подключения к Kubernetes. Minikube автоматически добавляет свой контекст при создании кластера.

**kubectl** — основная CLI-утилита для управления кластером Kubernetes. Используется для выполнения команд (`kubectl get`, `kubectl apply`, `kubectl describe`) и проверки состояния кластера.

**container runtime** — программа для запуска и управления контейнерами (Docker, containerd, CRI-O). Обязательный компонент для работы Minikube.

---

## Архитектура Minikube

| Компонент | Описание |
| :--- | :--- |
| **Однонодовый кластер** | Один узел control-plane (worker) — достаточно для изучения K8s |
| **Виртуализация** | Запускается в VM, Docker-контейнере или на bare metal |
| **Автоматическая настройка** | Minikube сам скачивает образы, настраивает kubeconfig |
| **Интеграция с kubectl** | Команды выполняются через `minikube kubectl -- <command>` |

---

## Требования и зависимости

### Обязательные требования

| Компонент | Назначение | Проверка |
| :--- | :--- | :--- |
| **Docker Desktop** (или другой runtime) | Среда исполнения контейнеров | `docker system info` |
| **Minikube** | Инструмент развёртывания кластера | `minikube version` |
| **kubectl** (опционально) | CLI для управления K8s | `kubectl version --client` |

> **Примечание:** Если kubectl не установлен, используйте встроенную версию: `minikube kubectl -- <command>`

### Системные требования

| Ресурс | Минимум | Рекомендовано |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4 ядра |
| **Память** | 2 ГБ | 4-8 ГБ |
| **Диск** | 20 ГБ | 40 ГБ |

---

## Сравнение с аналогами

| Инструмент | Подход | Безопасность | Сложность | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **[kind](../kind/kind_concepts.md)** | Контейнеры с стандартным K8s | Стандартная | Низкая | CI/CD, тестирование |
| **[talosctl](../local_cluster_with_talosctl.md)** | Контейнеры с Talos OS | mTLS, immutable | Средняя | Безопасные кластеры |
| **minikube** | VM с стандартным K8s | Стандартная | Низкая | Локальная разработка |

**Преимущества Minikube:**

- Полнофункциональная VM с реальным K8s
- Поддержка множества драйверов (Docker, VirtualBox, KVM, Hyperkit)
- Встроенные аддоны (dashboard, ingress, metrics-server, registry)
- Кроссплатформенность (Linux, macOS, Windows)

**Ограничения Minikube:**

- Тяжелее аналогов (требует VM)
- Медленнее запуск/остановка
- Ограниченная поддержка multi-node (требует дополнительных настроек)

---

## Основные команды Minikube

| Команда | Описание |
| :--- | :--- |
| `minikube start` | Запуск кластера |
| `minikube stop` | Остановка кластера (без удаления) |
| `minikube delete` | Удаление кластера и всех данных |
| `minikube status` | Проверка состояния кластера |
| `minikube kubectl -- <cmd>` | Выполнение команд kubectl |
| `minikube dashboard` | Открытие Kubernetes Dashboard |
| `minikube ip` | IP-адрес кластера |
| `minikube ssh` | Подключение к узлу по SSH |

---

## kubeconfig и контексты

Minikube автоматически управляет конфигурацией подключения:

1. **При запуске** (`minikube start`) создаётся запись в `~/.kube/config`
2. **Контекст** называется `minikube` по умолчанию
3. **kubectl** автоматически использует этот контекст

**Проверка контекста:**

```bash
kubectl config current-context
# Вывод: minikube

kubectl config get-contexts
# Список всех доступных контекстов
```

**Использование встроенного kubectl:**

```bash
# Если kubectl не установлен
minikube kubectl -- get nodes

# Проверка состояния кластера
minikube kubectl -- get pods -A
```

---

## Драйверы Minikube

Minikube поддерживает различные драйверы для запуска кластера:

| Драйвер | Платформа | Требования |
| :--- | :--- | :--- |
| **docker** | Linux/macOS/Windows | Docker Desktop |
| **virtualbox** | Linux/macOS/Windows | VirtualBox |
| **kvm2** | Linux | KVM, libvirt |
| **hyperkit** | macOS | Hyperkit |
| **hyper-v** | Windows | Hyper-V |
| **none** | Linux | Bare metal (требует root) |

**Выбор драйвера:**

```bash
# Запуск с конкретным драйвером
minikube start --driver=docker

# Установка драйвера по умолчанию
minikube config set driver docker
```

---

## Аддоны

Minikube включает набор встроенных аддонов для расширения функциональности:

| Аддон | Назначение |
| :--- | :--- |
| **dashboard** | Веб-интерфейс управления K8s |
| **ingress** | Ingress-контроллер для маршрутизации |
| **metrics-server** | Сбор метрик для `kubectl top` |
| **registry** | Локальный Docker Registry |
| **storage-provisioner** | Автоматическое создание PV |
| **helm** | Менеджер пакетов Helm |

**Управление аддонами:**

```bash
# Список доступных аддонов
minikube addons list

# Включение аддона
minikube addons enable ingress

# Отключение аддона
minikube addons disable registry
```

---

## Связанные документы

- **[Minikube: Практические сценарии](./minikube_practical_scenarios.md)** — установка, создание кластера, примеры
- **[kind: Локальные кластеры](../kind/kind_concepts.md)** — альтернатива на основе Docker
- **[Talos: Локальный кластер](../local_cluster_with_talosctl.md)** — альтернатива с Talos OS
- **[kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)** — работа с контекстами
- **[kubectl команды](../../ToolsUtilities/kubectl/kubectl_overview.md)** — справочник команд kubectl

---

## Внешние ресурсы

- **Официальная документация:** [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/)
- **GitHub:** [kubernetes/minikube](https://github.com/kubernetes/minikube)
- **Установка Docker Desktop:** [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
