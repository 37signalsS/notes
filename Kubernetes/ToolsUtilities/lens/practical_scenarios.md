# Lens: Практические сценарии

## Installation

**macOS (Homebrew):**

```bash
# OpenLens (открытая версия)
brew install --cask openlens

# Lens Desktop (коммерческая)
brew install --cask lens
```

**Windows (Chocolatey):**

```bash
choco install kubernetes-lens
```

**Linux (Ubuntu/Debian):**

```bash
# Добавление репозитория и установка
curl -fsSL https://api.k8slens.dev/repos/deb/gpg.key | sudo apt-key add -
echo "deb https://api.k8slens.dev/repos/deb/ /" | sudo tee /etc/apt/sources.list.d/lens-repo.list
sudo apt update && sudo apt install lens
```

**Linux (AppImage):**

```bash
# Загрузка последней версии: https://k8slens.dev/
chmod +x Lens-*.AppImage
./Lens-*.AppImage
```

---

## Initial Configuration

**Импорт kubeconfig:** Lens автоматически обнаруживает `~/.kube/config`. Для резервной копии: `cp ~/.kube/config ~/.kube/config.lens-backup`.

**Настройка путей:** `File > Preferences` (или `⌘/Ctrl + ,`) → **Kubernetes** → указать путь к kubeconfig, если отличается от стандартного.

---

## Metrics Configuration

По умолчанию метрики могут быть недоступны (`metrics not available`).

**Вариант 1: Встроенный Lens Metric Stack** — ПКМ на кластер → **Settings** → **Metric Stack** → **Install**. Lens развернёт Prometheus в кластере.

**Вариант 2: Существующий Prometheus** — `Cluster Settings > Metrics` → **Custom Prometheus** → URL: `http://prometheus-server.prometheus.svc.cluster.local:9090`.

**Вариант 3: kube-prometheus-stack через Helm:**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

URL в Lens: `http://prometheus-operated.monitoring.svc.cluster.local:9090`

---

## Helm Charts Management

**Просмотр:** выбрать кластер → **Helm** (левая панель) → отображаются все релизы.

**Установка:** `Helm > Charts` → найти чарт → **Install** → настроить values и namespace.

**Обновление:** `Helm > Releases` → выбрать релиз → **Upgrade** → изменить values/версию.

**Удаление:** `Helm > Releases` → выбрать релиз → **Delete**.

---

## Log Viewing and Analysis

**Просмотр логов пода:** `Workloads > Pods` → кликнуть на под → вкладка **Logs**.

**Множественные контейнеры:** выбрать контейнер из списка или включить **All Containers**.

**Фильтрация:** поиск по тексту (например, `error`), по времени (Last 1 hour, Last 24 hours, Custom range).

**Копирование:** кнопка **Copy** или выделение + `Ctrl+C`.

---

## Built-in Terminal

**Подключение:** `Workloads > Pods` → кликнуть на под → **Shell** или **Connect**.

**Примеры команд:**

```bash
env                          # переменные окружения
ls /etc/config               # файлы конфигурации
netstat -tlnp                # сетевые подключения
curl localhost:8080/health   # проверка health endpoint
```

---

## Resource Editing

**Редактирование YAML:** перейти к ресурсу → кликнуть → **Edit** (карандаш) → изменить → **Save**.

**Применение из файла:** `File > Apply from File` (или `⌘/Ctrl + Shift + A`) → выбрать YAML → подтвердить.

---

## Cluster Monitoring

**Обзор:** **Nodes** — статус узлов, CPU/memory; **Namespaces** — список и квоты; **Events** — последние события.

**Алерты:** `Config > Alerts` → настроить уведомления о критических событиях.

---

## Kubespray Integration

При использовании [Kubespray](../../Installation/Kubespray/kubespray_install/basic_concepts.md):

```bash
# admin.conf находится в: inventory/имя_кластера/artifacts/admin.conf
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config
# Lens автоматически обнаружит кластер
```

---

## Hotbar и Command Palette

**Hotbar** — панель быстрого доступа к часто используемым кластерам и ресурсам.

- **Добавление:** ПКМ на элемент → **Add to Hotbar**
- **Навигация:** `⌘/Ctrl + 1-9` для переключения между слотами
- **Управление:** ПКМ на слот → **Remove from Hotbar**

**Command Palette** — универсальный поиск и выполнение команд.

- **Вызов:** `⌘/Ctrl + Shift + P` или `⌘/Ctrl + P`
- **Поиск ресурсов:** ввести имя пода, deployment, namespace
- **Вызов действий:** `Restart`, `Delete`, `Edit`, `Scale`

---

## Port Forwarding

**Создание проброса:** `Workloads > Pods` → ПКМ на под → **Port Forward** → указать локальный и целевой порт.

**Управление:** `Network > Port Forwarding` — централизованный список всех активных пробросов.

---

## AI Assistant (Lens Prism)

**Настройка:** `Preferences > AI` → выбрать провайдера (OpenAI, Azure, совместимые API) → указать API key и endpoint.

**Возможности:**

- Генерация YAML-манифестов по описанию
- Объяснение ошибок и логов
- Рекомендации по конфигурации
- Prompt-инжиниринг для Kubernetes-задач

---

## Security Center

**Сканирование уязвимостей:** выбрать кластер → **Security Center** → **Scan**.

**Типы отчётов:**

- **Images** — уязвимости в образах контейнеров
- **Resources** — уязвимые ресурсы кластера
- **Roles** — избыточные права и роли

**Air-gapped режим:** сканирование в изолированных средах без выхода в интернет, экспорт отчётов.

---

## Lens Teamwork

**Создание пространства:** `Teamwork > Create Space` → указать имя → пригласить участников.

**Управление кластерами:** добавить кластер в пространство → настроить роли и разрешения для участников.

**Ролевая модель:** Admin, Editor, Viewer — настраиваемые права на чтение/запись/управление.

**Lens Cloud:** синхронизация данных пространства и кластеров через облачный сервис.

---

## Troubleshooting

**ZScaler / корпоративный прокси:** ошибка входа — настроить исключения SSL-инспекции или прокси в ZScaler.

**Integrity check error:** проверка целостности файлов не пройдена — переустановка или отключение блокирующих антивирусных правил.

**Pod shell connection error:** диагностика сетевых политик кластера, проверка прав RBAC для `exec`, доступности kubelet API.

**Metrics not available:** см. раздел [Metrics Configuration](#metrics-configuration) выше.

---

## Связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — требования, альтернативы, безопасность
