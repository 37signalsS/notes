# Сравнение Helm v2 и v3

Helm 3 ввёл ключевые архитектурные изменения: отказ от Tiller, переход на клиент-only модель и улучшение безопасности.

## Определения

| Термин | Описание |
|--------|----------|
| **Tiller** | Серверный компонент Helm 2 в кластере |
| **Chart API** | Версия формата чарта (v1/v2) |
| **CRD** | Custom Resource Definitions |

## Основные концепции

### Архитектурные различия

| Аспект | Helm v2 | Helm v3 |
|--------|---------|---------|
| Управляющий компонент | Tiller в кластере | Только клиент |
| Безопасность | Права для Tiller | RBAC пользователя |
| Хранение релизов | ConfigMaps в `kube-system` | Secrets в namespace релиза |
| Область имён | Часто кластерная | Уникальность в пределах namespace |
| Chart API | `apiVersion: v1` | `apiVersion: v2` |

### Безопасность

**Helm 2:**
- Tiller работал с повышенными привилегиями
- Сложная модель RBAC
- Центральная точка отказа

**Helm 3:**
- Клиент использует kubeconfig пользователя
- Нативный RBAC Kubernetes
- Нет серверного компонента

### Формат чартов

| Функция | Helm v2 | Helm v3 |
|---------|---------|---------|
| Типы чартов | Нет | `application`, `library` |
| Зависимости | `requirements.yaml` | `dependencies` в `Chart.yaml` |
| Lock-файл | Нет | `Chart.lock` |
| CRD | Как шаблоны | Каталог `crds/` |
| Локальные файлы | `~/.helm` | XDG-спецификация |

### Синтаксис команд

**Helm v2:**
```bash
helm install stable/mysql --name mydb --namespace prod
```

**Helm v3:**
```bash
helm install mydb bitnami/mysql --namespace prod
helm install --generate-name bitnami/mysql --namespace prod
```

## Практические сценарии

### Миграция чарта с v1 на v2

**Было (v2):**
```yaml
# requirements.yaml
dependencies:
- name: redis
  version: "~10.5"
  repository: "https://charts.example.com"
```

**Стало (v3):**
```yaml
# Chart.yaml
apiVersion: v2
name: myapp
type: application
version: 0.1.0
dependencies:
- name: redis
  version: "~17.0"
  repository: "https://charts.example.com"
```

```bash
helm dependency update
# Создаёт Chart.lock
```

### CRD в Helm 3

```
mychart/
├── crds/              # Применяется до шаблонов
│   └── myresource.yaml
├── templates/
└── values.yaml
```

### Трёхстороннее слияние (Helm 3)

Helm 3 использует стратегию three-way merge:
- Желаемое состояние (чарт)
- Последняя ревизия
- "Живое" состояние в кластере

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции
- [Структура Helm-чарта](./helm_chart_structure.md) — формат Chart.yaml
- [Управление версиями релизов](./helm_release_versioning.md) — хранение ревизий
