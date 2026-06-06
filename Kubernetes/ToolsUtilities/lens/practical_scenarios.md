# Lens: Практические сценарии

## Определения

**Kubeconfig** — конфигурационный файл в формате YAML (Yet Another Markup Language), содержащий параметры подключения к кластерам Kubernetes.

**Helm** — менеджер пакетов для Kubernetes, используемый для управления жизненным циклом приложений (чартов).

**Lens Metric Stack** — встроенный стек мониторинга на базе Prometheus, развертываемый внутри кластера для визуализации метрик в IDE (Integrated Development Environment).

**Lens Prism** — встроенный AI-ассистент (Artificial Intelligence), предоставляющий функции генерации манифестов и анализа логов.

---

## Основные концепции

### Управление конфигурациями
Lens основывает свою работу на анализе локальных и внешних файлов конфигурации. Основной механизм доступа — чтение контекстов из стандартных путей или вручную добавленных файлов.

### Расширяемость
Функционал IDE дополняется через систему расширений (Extensions), которые позволяют интегрировать сторонние инструменты (ArgoCD, Flux, Trivy) непосредственно в интерфейс управления.

### Визуализация и инспекция
Концепция Lens заключается в предоставлении "единого окна" для мониторинга ресурсов, просмотра логов и интерактивного взаимодействия с контейнерами через встроенный терминал.

---

## Практические сценарии

### Установка

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
# Загрузка последней версии с официального сайта
chmod +x Lens-*.AppImage
./Lens-*.AppImage
```

### Начальная настройка

**Подключение к кластеру:** Lens использует стандартные файлы `kubeconfig`.

- **Автоматическое обнаружение:** сканирует `~/.kube/config`, все найденные контексты отображаются в списке кластеров. Для резервной копии используйте: `cp ~/.kube/config ~/.kube/config.lens-backup`.
- **Ручное добавление:** `File > Add Cluster` (или `⌘/Ctrl + K`) → вставить содержимое kubeconfig → **Add Cluster**.
- **Из файла:** `File > Add Cluster` → выбрать файл kubeconfig → подтвердить.

**Настройка путей:** `File > Preferences` (или `⌘/Ctrl + ,`) → **Kubernetes** → указать путь к kubeconfig, если он отличается от стандартного.

### Настройка метрик

По умолчанию метрики могут быть недоступны (`metrics not available`).

**Вариант 1: Встроенный Lens Metric Stack** — ПКМ на кластер → **Settings** → **Metric Stack** → **Install**. Lens развернет Prometheus в кластере.

**Вариант 2: Существующий Prometheus** — `Cluster Settings > Metrics` → **Custom Prometheus** → URL (Uniform Resource Locator): `http://prometheus-server.prometheus.svc.cluster.local:9090`.

**Вариант 3: kube-prometheus-stack через Helm:**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```
URL в Lens: `http://prometheus-operated.monitoring.svc.cluster.local:9090`

### Управление расширениями (Extensions)

Расширения позволяют добавить специфический функционал в IDE.

**Популярные расширения:**
- **Lens Metrics** — улучшенные метрики и дашборды
- **Port Forwarder** — расширенное управление пробросом портов
- **YAML Editor** — продвинутые функции редактирования
- **GitOps** — интеграция с инструментами ArgoCD и Flux

**Установка:** `File > Preferences > Extensions` → найти нужное расширение в списке или указать путь → нажать **Install**.

### Управление Helm-чартами

**Просмотр:** выбрать кластер → **Helm** (левая панель) → отображаются все релизы.

**Установка:** `Helm > Charts` → найти чарт → **Install** → настроить значения (values) и пространство имен (namespace).

**Обновление:** `Helm > Releases` → выбрать релиз → **Upgrade** → изменить конфигурацию или версию.

### Просмотр и анализ логов

**Просмотр логов пода:** `Workloads > Pods` → кликнуть на под → вкладка **Logs**.

**Множественные контейнеры:** выбрать контейнер из списка или включить **All Containers**.

**Фильтрация:** поиск по тексту (например, `error`), по времени (Last 1 hour, Last 24 hours).

### Встроенный терминал

**Подключение:** `Workloads > Pods` → кликнуть на под → **Shell** или **Connect**.

**Примеры команд:**
```bash
env                          # переменные окружения
ls /etc/config               # файлы конфигурации
netstat -tlnp                # сетевые подключения
curl localhost:8080/health   # проверка состояния приложения
```

### Редактирование ресурсов

**Редактирование YAML:** перейти к ресурсу → кликнуть → **Edit** (карандаш) → изменить → **Save**.

**Применение из файла:** `File > Apply from File` (или `⌘/Ctrl + Shift + A`) → выбрать YAML → подтвердить.

### Мониторинг кластера

**Обзор:** **Nodes** — статус узлов, потребление ресурсов; **Namespaces** — список и квоты; **Events** — последние события в кластере.

**Алерты:** `Config > Alerts` → настройка уведомлений о критических событиях.

### Интеграция с Kubespray

При использовании [Kubespray](../../Installation/Kubespray/kubespray_install/basic_concepts.md):
```bash
# Копирование конфига из директории артефактов
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config
```

### Hotbar и Command Palette

**Hotbar** — панель быстрого доступа.
- **Добавление:** ПКМ на элемент → **Add to Hotbar**
- **Навигация:** `⌘/Ctrl + 1-9` для переключения

**Command Palette** — универсальный поиск.
- **Вызов:** `⌘/Ctrl + Shift + P`
- **Действия:** `Restart`, `Delete`, `Edit`, `Scale`

### Проброс портов (Port Forwarding)

**Создание:** `Workloads > Pods` → ПКМ на под → **Port Forward** → указать локальный и целевой порт.

**Управление:** `Network > Port Forwarding` — централизованный список активных пробросов.

### AI-ассистент (Lens Prism)

**Настройка:** `Preferences > AI` → выбрать провайдера (OpenAI, Azure) → указать API (Application Programming Interface) ключ.

**Возможности:**
- Генерация манифестов по текстовому описанию.
- Объяснение причин ошибок в логах.

### Центр безопасности (Security Center)

**Сканирование:** выбрать кластер → **Security Center** → **Scan**. Использует Trivy для поиска уязвимостей в образах и конфигурациях.

**Работа в изолированной среде (Air-gapped):** сканирование без доступа к интернету с использованием локальных баз данных уязвимостей.

### Командная работа (Lens Teamwork)

**Пространства (Spaces):** `Teamwork > Create Space` → приглашение участников.

**Ролевая модель:** настройка прав Admin, Editor, Viewer для управления общими кластерами.

**Lens Cloud:** сервис облачной синхронизации настроек и доступов.

### Корпоративные интеграции

**SSO (Single Sign-On) и SCIM (System for Cross-domain Identity Management):** настройка централизованной аутентификации через Microsoft Entra ID (Azure AD), Okta или JumpCloud. Выполняется в настройках организации.

---

## Дополнительная информация

### Устранение неполадок

**Корпоративные прокси (ZScaler):** ошибки аутентификации — настроить исключения SSL (Secure Sockets Layer) инспекции.

**Ошибка проверки целостности (Integrity check error):** переустановка приложения или настройка исключений антивирусного ПО.

**Ошибка подключения к Shell:** проверка прав RBAC (Role-Based Access Control) для операции `exec` и доступности API-сервера.

### Связанные ресурсы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация о Lens
- [Дополнительная информация](./advanced_topics.md) — требования, альтернативы, безопасность
- [kubeswitches](../kubeswitches/kubeswitch_overview.md) — управление контекстами Kubernetes
