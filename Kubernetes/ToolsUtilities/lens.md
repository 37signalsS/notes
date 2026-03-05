# Lens: Графический интерфейс для Kubernetes

## 1. Определения

**Lens** (теперь **OpenLens** / **Lens Desktop**) — это мощная интегрированная среда разработки (IDE) для Kubernetes, предназначенная для управления кластерами в режиме реального времени. Она предоставляет богатый графический интерфейс, который упрощает взаимодействие с API Kubernetes и визуализирует состояние кластера.

**Важно:** Проект Lens претерпел изменения в лицензировании. Открытая версия теперь называется **OpenLens**, а коммерческая — **Lens Desktop**.

## 2. Основные концепции

### Ключевые возможности

| Возможность | Описание |
| :--- | :--- |
| **Управление несколькими кластерами** | Переключение между кластерами из одного интерфейса |
| **Визуализация ресурсов** | Отображение всех объектов K8s и их связей |
| **Метрики в реальном времени** | Интеграция с Prometheus для CPU, memory, network |
| **Встроенный терминал** | Доступ к оболочке узлов и контейнеров |
| **Управление Helm-чартами** | Просмотр, установка, обновление релизов |
| **Логи контейнеров** | Просмотр логов для одного или нескольких подов |
| **Редактор манифестов** | Редактирование YAML с подсветкой и валидацией |
| **Расширения** | Поддержка плагинов для расширения функциональности |

### Архитектура

```
┌─────────────────────────────────────────────────────┐
│                    Lens Desktop                     │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │   Cluster   │  │   Cluster   │  │   Cluster   │ │
│  │     Dev     │  │    Stage    │  │    Prod     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
├─────────────────────────────────────────────────────┤
│              Kubernetes API (kubeconfig)            │
└─────────────────────────────────────────────────────┘
```

### Подключение к кластеру

Lens использует стандартные файлы `kubeconfig` для подключения.

**Автоматическое обнаружение:**
- Lens автоматически сканирует `~/.kube/config`
- Все найденные контексты отображаются в списке кластеров

**Ручное добавление:**
1. Скопируйте содержимое kubeconfig файла
2. В Lens: `File > Add Cluster` (или `⌘/Ctrl + K`)
3. Вставьте содержимое kubeconfig
4. Нажмите **Add Cluster**

**Из файла:**
1. В Lens: `File > Add Cluster`
2. Выберите файл kubeconfig
3. Подтвердите добавление

### Поддержка платформ

| Платформа | Поддержка | Примечание |
| :--- | :--- | :--- |
| **Windows** | ✅ | x64, arm64 |
| **macOS** | ✅ | Intel, Apple Silicon |
| **Linux** | ✅ | AppImage, deb, rpm |

## 3. Практические сценарии

### 3.1. Установка

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
# Добавление репозитория
curl -fsSL https://api.k8slens.dev/repos/deb/gpg.key | sudo apt-key add -
echo "deb https://api.k8slens.dev/repos/deb/ /" | sudo tee /etc/apt/sources.list.d/lens-repo.list

# Установка
sudo apt update
sudo apt install lens
```

**Linux (AppImage):**

```bash
# Загрузка
wget https://api.k8slens.dev/releases/download/v5.9.0/Lens-5.9.0-latest.20240103.1-linux-x86_64.AppImage

# Запуск
chmod +x Lens-*.AppImage
./Lens-*.AppImage
```

### 3.2. Первоначальная настройка

**Импорт kubeconfig:**

```bash
# Копирование существующего kubeconfig
cp ~/.kube/config ~/.kube/config.lens-backup

# Lens автоматически обнаружит ~/.kube/config
```

**Настройка путей:**

1. Откройте `File > Preferences` (или `⌘/Ctrl + ,`)
2. Перейдите в раздел **Kubernetes**
3. Укажите путь к kubeconfig, если отличается от стандартного

### 3.3. Отображение метрик производительности

По умолчанию метрики могут быть недоступны (`metrics not available`).

**Вариант 1: Установка встроенного Prometheus (Lens Metric Stack)**

1. Кликните правой кнопкой мыши на кластер в левой панели
2. Выберите **Settings**
3. Прокрутите до раздела **Metric Stack**
4. Нажмите **Install**

Lens развернет адаптированную версию Prometheus в кластере.

**Вариант 2: Подключение существующего Prometheus**

1. `Cluster Settings > Metrics`
2. Выберите **Custom Prometheus**
3. Укажите URL вашего Prometheus:
   ```
   http://prometheus-server.prometheus.svc.cluster.local:9090
   ```

**Вариант 3: Через kube-prometheus-stack**

```bash
# Установка prometheus-stack через Helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace

# В Lens: Settings > Metrics > Prometheus
# URL: http://prometheus-operated.monitoring.svc.cluster.local:9090
```

### 3.4. Управление Helm-чартами

**Просмотр установленных чартов:**

1. Выберите кластер
2. Перейдите в раздел **Helm** (левая панель)
3. Отобразятся все установленные релизы

**Установка нового чарта:**

1. `Helm > Charts`
2. Найдите нужный чарт (например, `nginx-ingress`)
3. Нажмите **Install**
4. Настройте values и namespace
5. Подтвердите установку

**Обновление релиза:**

1. `Helm > Releases`
2. Выберите релиз
3. Нажмите **Upgrade**
4. Измените values или версию чарта

**Удаление релиза:**

1. `Helm > Releases`
2. Выберите релиз
3. Нажмите **Delete**

### 3.5. Просмотр и анализ логов

**Просмотр логов пода:**

1. Перейдите в **Workloads > Pods**
2. Кликните на под
3. Выберите вкладку **Logs**

**Множественные контейнеры:**

Если под содержит несколько контейнеров:
- Выберите контейнер из выпадающего списка
- Или включите **All Containers** для просмотра всех логов

**Фильтрация логов:**

```
# Поиск по тексту
error

# По времени
Last 1 hour
Last 24 hours
Custom range
```

**Копирование логов:**

- Кнопка **Copy** для копирования в буфер
- Или выделите текст и используйте `Ctrl+C`

### 3.6. Встроенный терминал

**Подключение к контейнеру:**

1. Перейдите в **Workloads > Pods**
2. Кликните на под
3. Нажмите **Shell** (если доступен bash) или **Connect**

**Команды в терминале:**

```bash
# Проверка переменных окружения
env

# Просмотр файлов конфигурации
ls /etc/config
cat /etc/config/app.properties

# Проверка сетевых подключений
netstat -tlnp
curl localhost:8080/health
```

### 3.7. Редактирование ресурсов

**Редактирование YAML:**

1. Перейдите к ресурсу (например, **Workloads > Deployments**)
2. Кликните на ресурс
3. Нажмите **Edit** (карандаш)
4. Измените YAML
5. Нажмите **Save**

**Применение манифеста из файла:**

1. `File > Apply from File` (или `⌘/Ctrl + Shift + A`)
2. Выберите YAML файл
3. Подтвердите применение

### 3.8. Мониторинг состояния кластера

**Обзор кластера:**

- **Nodes** — статус узлов, метрики CPU/memory
- **Namespaces** — список и квоты namespace'ов
- **Events** — последние события кластера

**Алерты и уведомления:**

1. Перейдите в **Config > Alerts**
2. Настройте уведомления о критических событиях

### 3.9. Интеграция с Kubespray

При использовании [Kubespray](../Installation/Kubespray/installation.md):

```bash
# Получение admin.conf
# Файл находится в: inventory/имя_кластера/artifacts/admin.conf

# Копирование в стандартное расположение
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config

# Lens автоматически обнаружит кластер
```

## 4. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено до 1.32 |
| ОЗУ | 4 GB | Минимум, рекомендуется 8 GB |
| Дисковое пространство | 500 MB | Для установки |

### OpenLens vs Lens Desktop

| Характеристика | OpenLens | Lens Desktop |
| :--- | :--- | :--- |
| **Лицензия** | MIT (открытая) | Commercial |
| **Расширения** | ✅ | ✅ |
| **Метрики** | ✅ | ✅ |
| **Поддержка** | Community | Commercial |
| **Обновления** | Реже | Чаще |

### Расширения (Extensions)

**Популярные расширения:**

- **Lens Metrics** — улучшенные метрики
- **Port Forwarder** — управление port forwarding
- **YAML Editor** — продвинутый редактор
- **GitOps** — интеграция с ArgoCD/Flux

**Установка расширений:**

1. `File > Preferences > Extensions`
2. Найдите расширение в каталоге
3. Нажмите **Install**

### Безопасность

1. **Защита kubeconfig:**
   - Файлы kubeconfig содержат чувствительные данные
   - Используйте файловые разрешения `600`

2. **RBAC:**
   - Lens использует права из kubeconfig
   - Ограничьте права для production-кластеров

3. **Отключение телеметрии:**
   ```
   Preferences > Application > Telemetry
   ```

### Ограничения

- **Ресурсоёмкость** — может потреблять значительную память
- **Не заменяет kubectl** — сложные операции требуют CLI
- **Проприетарная версия** — Lens Desktop имеет платные функции

### Альтернативы

| Инструмент | Тип | Преимущества |
| :--- | :--- | :--- |
| **[Octant](https://github.com/vmware-tanzu/octant)** | Open Source | Лёгкий, от VMware |
| **k9s** | TUI | Терминальный интерфейс, быстрый |
| **kubectl + vim** | CLI | Полный контроль, скриптуемость |

### Связанные документы

- **[kubeswitches](./kubeswitches.md)** — управление контекстами
- **[Prometheus](../../Prometheus/prometheus_api.md)** — система метрик
- **[Helm](./Helm/helm_overview.md)** — управление чартами
- **[Kubespray](../Installation/Kubespray/installation.md)** — установка кластеров

### Репозиторий и документация

- [GitHub: OpenLens](https://github.com/MuhammedKalkan/openlens)
- [GitHub: Lens](https://github.com/lensapp/lens)
- [Официальный сайт](https://k8slens.dev/)
- [Документация](https://docs.k8slens.dev/)
