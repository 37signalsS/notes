# Lens: Практические сценарии

## 3.1. Установка

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

---

## 3.2. Первоначальная настройка

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

---

## 3.3. Отображение метрик производительности

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

---

## 3.4. Управление Helm-чартами

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

---

## 3.5. Просмотр и анализ логов

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

---

## 3.6. Встроенный терминал

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

---

## 3.7. Редактирование ресурсов

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

---

## 3.8. Мониторинг состояния кластера

**Обзор кластера:**

- **Nodes** — статус узлов, метрики CPU/memory
- **Namespaces** — список и квоты namespace'ов
- **Events** — последние события кластера

**Алерты и уведомления:**

1. Перейдите в **Config > Alerts**
2. Настройте уведомления о критических событиях

---

## 3.9. Интеграция с Kubespray

При использовании [Kubespray](../Installation/Kubespray/installation.md):

```bash
# Получение admin.conf
# Файл находится в: inventory/имя_кластера/artifacts/admin.conf

# Копирование в стандартное расположение
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config

# Lens автоматически обнаружит кластер
```

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — требования, альтернативы, безопасность
