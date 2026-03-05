# LVM: Расширенные темы — Дополнительная информация

## Диагностика и troubleshooting

### Частые проблемы

| Проблема | Команда проверки | Решение |
| :--- | :--- | :--- |
| VG не активируется | `vgscan`, `vgdisplay` | Проверить наличие всех PV |
| LV не монтируется | `lvdisplay`, `dmesg` | Проверить ФС (`fsck`) |
| `/boot` на LVM | `mount | grep /boot` | Переместить на обычный раздел |
| Миграция зависла | `pvmove --status` | Не прерывать! Дождаться завершения |

### Команды диагностики

```bash
# Полная информация о структуре
pvs -o+pv_mda_size,vgs,lvs
vgs -o+vg_mda_size,pvs,lvs
lvs -o+lv_mda_size,vg,pvs

# Проверка целостности метаданных
pvck /dev/sdb1
vgck my_vg

# Поиск потерянных VG/LV
vgscan
lvscan
```

---

## Связанные темы

| Тема | Файл |
| :--- | :--- |
| Базовые концепции LVM | [overview_concepts.md](./overview_concepts.md) |
| Операции управления | [management_operations.md](./management_operations.md) |
| Снимки | [snapshots.md](./snapshots.md) |
| Тонкое провизионирование | [thin_provisioning.md](./thin_provisioning.md) |
| Шифрование дисков | ../../Security/encryption.md (dm-crypt/LUKS) |
| Загрузка Linux | ../../Boot/grub.md |

---

## Внешние ресурсы

- [LVM HOWTO (Linux Foundation)](https://wiki.linuxfoundation.org/lvm/start)
- [Red Hat: LVM Administration](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_logical_volumes/)
- [Arch Wiki: LVM](https://wiki.archlinux.org/title/LVM)

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — загрузка с LVM, файловые системы
- [Практические сценарии](./practical_scenarios.md) — операции с пространством, swap, восстановление
