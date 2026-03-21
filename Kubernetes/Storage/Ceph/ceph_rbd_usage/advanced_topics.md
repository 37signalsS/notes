# RBD: Дополнительная информация

## Производительность

### Оптимизация параметров монтирования

```bash
mount -o noatime,nodiratime,discard /dev/rbd0 /mnt/rbd
```

| Опция | Описание |
|-------|----------|
| `noatime` | Не обновлять время доступа |
| `nodiratime` | Не обновлять время доступа к директориям |
| `discard` | Включить TRIM для тонкого выделения |

### Бенчмаркинг

```bash
# Тест скорости записи
fio --name=write --ioengine=libaio --rw=write --bs=4k \
  --direct=1 --numjobs=1 --size=1G --runtime=60 \
  --filename=/dev/rbd0

# Тест скорости чтения
fio --name=read --ioengine=libaio --rw=read --bs=4k \
  --direct=1 --numjobs=1 --size=1G --runtime=60 \
  --filename=/dev/rbd0
```

---

## Бэкап и восстановление

```bash
# Экспорт образа
rbd export kube/my-image /backup/my-image.img

# Импорт образа
rbd import /backup/my-image.img kube/my-image-restored

# Инкрементальный бэкап (требует object-map, fast-diff)
rbd export-diff kube/my-image@snap1 /backup/diff.snap1
```

---

## Ссылки

- [Обзор Ceph](../ceph_overview.md)
- [Официальная документация RBD](https://docs.ceph.com/en/latest/rbd/)

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — установка, управление, монтирование
