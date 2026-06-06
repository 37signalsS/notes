# Сравнение Helm v2 и v3

> **⚠️ EOL Warning:** Helm 2 достиг EOL (End of Life) 13 ноября 2020 года. Финальная версия — 2.17.0. Для всех проектов используйте Helm 3.

Helm 3 ввёл ключевые архитектурные изменения: отказ от серверного компонента Tiller, переход на клиент-only модель и улучшение безопасности через нативный RBAC (Role-Based Access Control).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Tiller** | Серверный компонент Helm 2, работавший в кластере Kubernetes с повышенными привилегиями |
| **apiVersion** | Версия формата чарта: `v1` (Helm 2) или `v2` (Helm 3) |
| **Chart API v2** | Расширенный формат чарта с поддержкой типов `application`/`library` и встроенными зависимостями |
| **Three-way merge** | Стратегия слияния: желаемое состояние + последняя ревизия + текущее состояние в кластере |

---

## Базовые концепции

### Архитектурные различия

| Аспект | Helm v2 | Helm v3 |
|--------|---------|---------|
| **Управляющий компонент** | Tiller в кластере с повышенными привилегиями | Только клиент; прямое взаимодействие с Kubernetes API |
| **Безопасность** | RBAC для Tiller; сложная модель разрешений | RBAC пользователя через kubeconfig; нативная интеграция |
| **Хранение релизов** | ConfigMaps в namespace `kube-system` | Secrets в namespace целевого релиза |
| **Уникальность имён** | Глобальная уникальность имён релизов | Уникальность в пределах namespace |
| **Chart API** | `apiVersion: v1` | `apiVersion: v2` |

### Безопасность

**Helm 2 (Tiller):**

- Tiller работал с широкими привилегиями в кластере
- Необходимость настройки сложной модели RBAC для Tiller
- Центральная точка отказа и потенциальная угроза безопасности
- Все операции выполнялись от имени сервисного аккаунта Tiller

**Helm 3 (Client-only):**

- Клиент использует учётные данные пользователя из kubeconfig
- Нативная интеграция с RBAC Kubernetes
- Никакого серверного компонента в кластере
- Операции выполняются с правами текущего пользователя

### Формат чартов (Chart API)

| Функция | Helm v2 (v1) | Helm v3 (v2) |
|---------|--------------|--------------|
| **Типы чартов** | Только application | `application` и `library` |
| **Зависимости** | В отдельном файле `requirements.yaml` | Встроены в `Chart.yaml`, секция `dependencies` |
| **Lock-файл** | Не поддерживался | `Chart.lock` для фиксации версий |
| **CRD (Custom Resource Definition)** | Обрабатывались как обычные шаблоны | Специальная директория `crds/` (применяется до шаблонов) |
| **Локальное хранилище** | `~/.helm` | XDG Base Directory Specification (`~/.cache/helm`, `~/.config/helm`) |

### Стратегия слияния

**Helm 2** использовал двустороннее слияние (two-way merge):

- Сравнение желаемого состояния (чарт) и предыдущей ревизии

**Helm 3** использует трёхстороннее слияние (three-way merge):

- Желаемое состояние (новый чарт)
- Последняя ревизия Helm
- Текущее "живое" состояние в кластере

**Преимущества three-way merge:**

- Корректная обработка изменений, внесённых вне Helm
- Уменьшение количества конфликтов при обновлениях
- Более предсказуемое поведение при редактировании ресурсов вручную

### Синтаксис команд

**Helm v2:**

```bash
# Установка с указанием имени через флаг
helm install stable/mysql --name mydb --namespace prod

# Установка без имени (автогенерация)
helm install stable/mysql --namespace prod
```

**Helm v3:**

```bash
# Установка с именем как позиционный аргумент
helm install mydb bitnami/mysql --namespace prod

# Автогенерация имени
helm install --generate-name bitnami/mysql --namespace prod

# Сокращённая запись upgrade или install
helm upgrade --install mydb bitnami/mysql --namespace prod
```

---

## Практические сценарии

### Миграция чарта с apiVersion v1 на v2

**Было (Helm 2, requirements.yaml):**

```yaml
# requirements.yaml
dependencies:
- name: redis
  version: "~10.5"
  repository: "https://charts.bitnami.com/bitnami"
- name: postgresql
  version: "8.x.x"
  repository: "https://charts.bitnami.com/bitnami"
```

```bash
# Helm 2: обновление зависимостей
helm dependency update
# Нет lock-файла
```

**Стало (Helm 3, Chart.yaml):**

```yaml
# Chart.yaml
apiVersion: v2
name: myapp
description: My application chart
type: application
version: 1.0.0
appVersion: "2.0.0"
dependencies:
- name: redis
  version: "~17.0"
  repository: "https://charts.bitnami.com/bitnami"
  condition: redis.enabled
- name: postgresql
  version: "12.x.x"
  repository: "https://charts.bitnami.com/bitnami"
```

```bash
# Helm 3: обновление зависимостей и создание Chart.lock
helm dependency update
# Создаёт/обновляет Chart.lock с точными версиями
```

### Работа с CRD в Helm 3

```text
mychart/
├── crds/                      # CRD применяются ДО шаблонов
│   └── myresource.yaml
├── templates/
│   ├── deployment.yaml
│   └── service.yaml
├── Chart.yaml
└── values.yaml
```

**Важно:** CRD в директории `crds/` не управляются как часть релиза (`helm uninstall` не удалит их). Для управляемых CRD используйте обычные шаблоны с условиями.

### Library Charts

```yaml
# Chart.yaml для library chart
apiVersion: v2
name: mylib
description: Library chart with common templates
type: library  # <-- отличие от application
version: 1.0.0
```

Library charts содержат переиспользуемые шаблоны, но не создают собственных ресурсов. Используются как зависимости для application charts.

### Проверка версии Helm

```bash
helm version
# Helm 2: показывает версию клиента и сервера (Tiller)
# Helm 3: показывает только версию клиента
```

### Конвертация релизов

```bash
# Миграция релиза из Helm 2 в Helm 3 (плагин helm-2to3, устарел)
helm 2to3 convert my-release

# Helm 3 автоматически работает с чартами apiVersion: v1
# Для использования новых функций обновите до apiVersion: v2
```

---

## Дополнительная информация

Файл содержит сравнительный анализ; детали архитектуры см. в [Обзор Helm](./helm_overview.md), формат чартов — в [Структура Helm-чарта](./helm_chart_structure.md), версионирование — в [Управление версиями релизов](./helm_release_versioning.md). Плагин миграции описан в [Плагины Helm](./helm_plugins.md).