# RBD: Управление образами

## Определения и базовые концепции

**Image (Образ)** — основной объект RBD, виртуальный диск, хранящийся как набор объектов в кластере Ceph.

**Snapshots и Clones:**

| Термин | Описание |
|--------|----------|
| **Snapshot** | Моментальная копия образа (read-only) |
| **Clone** | Записываемый образ, созданный из снапшота |
| **Protect** | Защита снапшота от удаления (обязательна для клонирования) |

**Trash (Корзина)** — механизм безопасного удаления: образ сначала перемещается в trash, затем удаляется окончательно.

---

## Практические сценарии

### Создание образа

```bash
# Базовое создание (размер в МБ)
rbd create --size 10240 --pool kube my-image

# С указанием функций (рекомендуется)
rbd create --size 10240 --pool kube \
  --image-features layering,exclusive-lock,object-map,fast-diff \
  my-image
```

> **Примечание:** `--object-size` задаёт размер объекта RADOS (по умолчанию 4 МБ). Увеличение может улучшить производительность при последовательном доступе.

### Получение информации

```bash
# Список образов в пуле
rbd ls -p kube

# Детальная информация об образе
rbd info kube/my-image

# Статистика использования (фактический размер на диске)
rbd du -p kube
```

### Изменение размера

```bash
# Увеличение (безопасная операция)
rbd resize --size 20480 kube/my-image

# Уменьшение (требует подтверждения)
rbd resize --size 5120 kube/my-image --allow-shrink
```

> **Внимание:** Уменьшение размера необратимо при потере данных. Убедитесь, что используемое пространство меньше нового размера.

### Удаление образа

```bash
# Прямое удаление
rbd rm kube/my-image

# Безопасное удаление через trash
rbd trash mv kube/my-image        # Перемещение в корзину
rbd trash rm kube/my-image        # Окончательное удаление
```

### Управление снапшотами

```bash
# Создание снапшота
rbd snap create kube/my-image@snap1

# Список снапшотов
rbd snap ls kube/my-image

# Откат к снапшоту (образ должен быть отмаплен)
rbd snap rollback kube/my-image@snap1

# Удаление снапшота
rbd snap rm kube/my-image@snap1

# Удаление всех снапшотов
rbd snap purge kube/my-image
```

### Клонирование

```bash
# Защита снапшота (обязательно перед клонированием)
rbd snap protect kube/my-image@snap1

# Создание клона
rbd clone kube/my-image@snap1 kube/clone-image

# Снятие защиты (после удаления всех клонов)
rbd snap unprotect kube/my-image@snap1
```

---

## Дополнительная информация

- [Официальная документация RBD](https://docs.ceph.com/en/latest/rbd/rbd-operations/)
- [Определения и концепции](./definitions_and_concepts.md) — image-features, архитектура
- [Установка и настройка](./installation_and_setup.md) — установка клиента
- [Маппинг и монтирование](./mapping_and_mounting.md) — работа с устройствами
