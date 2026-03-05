# RBD: Управление образами

## 1. Создание образа

```bash
# Создание образа 10 ГБ
rbd create --size 10240 --pool kube my-image

# С указанием функций
rbd create --size 10240 --pool kube \
  --image-features layering,exclusive-lock,object-map,fast-diff \
  my-image

# Thin provisioning (место выделяется по мере записи)
rbd create --size 10240 --pool kube --object-size 4096 my-image
```

---

## 2. Информация об образе

```bash
# Список образов в пуле
rbd ls -p kube

# Детальная информация
rbd info kube/my-image

# Статистика использования
rbd du -p kube
```

---

## 3. Изменение размера

```bash
# Увеличение размера
rbd resize --size 20480 kube/my-image

# Уменьшение (осторожно!)
rbd resize --size 5120 kube/my-image --allow-shrink
```

---

## 4. Удаление образа

```bash
# Удаление
rbd rm kube/my-image

# Перемещение в trash (безопасное удаление)
rbd trash mv kube/my-image
rbd trash rm kube/my-image  # Окончательное удаление
```

---

## 5. Снапшоты и клонирование

### Создание снапшота

```bash
# Создание
rbd snap create kube/my-image@snap1

# Список снапшотов
rbd snap ls kube/my-image
```

### Откат к снапшоту

```bash
# Откат (образ должен быть размапплен!)
rbd snap rollback kube/my-image@snap1
```

### Клонирование

```bash
# Защита снапшота (обязательно для клонирования)
rbd snap protect kube/my-image@snap1

# Создание клона
rbd clone kube/my-image@snap1 kube/clone-image

# Снятие защиты
rbd snap unprotect kube/my-image@snap1
```

### Удаление снапшотов

```bash
# Удаление одного снапшота
rbd snap rm kube/my-image@snap1

# Удаление всех снапшотов
rbd snap purge kube/my-image
```

---

## Ссылки

- **[Установка и настройка](./installation_and_setup.md)** — установка клиента
- **[Маппинг и монтирование](./mapping_and_mounting.md)** — работа с устройствами
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
