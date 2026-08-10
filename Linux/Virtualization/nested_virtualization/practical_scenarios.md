# Вложенная виртуализация — Практические сценарии

В данном файле приведены практические инструкции по настройке вложенной виртуализации для различных архитектур (x86, ARM64), платформ управления (Libvirt, Proxmox, Vagrant) и облачных провайдеров.

## Определения

**Nested VT-x / SVM** — параметры модулей ядра KVM (`kvm_intel` и `kvm_amd`), активирующие проброс аппаратных инструкций виртуализации в гостевую систему.

**host-passthrough** — режим работы CPU, при котором ВМ получает все флаги и инструкции физического процессора. Обязательное условие для работы вложенной виртуализации с минимальными потерями производительности.

**Enlightened VMCS** — технология оптимизации для гипервизоров Microsoft (Hyper-V/Azure), снижающая накладные расходы на переключение контекста во вложенных средах за счёт прямого взаимодействия гипервизоров L0 и L1.

## Базовые концепции

### Порядок настройки (Workflow)

Реализация вложенности всегда требует двух последовательных шагов:
1.  **Уровень L0 (Хост):** Активация поддержки вложенности в параметрах модуля ядра или загрузчика ОС.
2.  **Уровень L1 (ВМ):** Настройка конфигурации виртуальной машины для проброса функций CPU (режим `host` или `passthrough`).

### Проверка аппаратной готовности
Перед началом настройки убедитесь, что на физическом хосте установлена утилита `virt-host-validate` (пакет `libvirt-clients`).

```bash
virt-host-validate
# → QEMU: Checking for device assignment IOMMU support : PASS
```

## Практические сценарии

### Сценарий 1: Настройка физического хоста (L0)

#### Архитектура x86_64 (Intel и AMD)
1. **Проверка статуса:**
   ```bash
   # Intel
   cat /sys/module/kvm_intel/parameters/nested
   # AMD
   cat /sys/module/kvm_amd/parameters/nested
   # → 'Y' или '1' — включено, 'N' или '0' — выключено.
   ```
2. **Активация (если выключено):**
   Создайте файл `/etc/modprobe.d/kvm-nested.conf`:
   ```text
   # Для систем Intel
   options kvm_intel nested=1
   # Для систем AMD (обычно включено по умолчанию в ядрах 5.15+)
   options kvm_amd nested=1
   ```
3. **Перезагрузка модулей:**
   ```bash
   sudo modprobe -r kvm_intel && sudo modprobe kvm_intel
   ```

#### Архитектура ARM64 (Apple Silicon, Ampere)
Требуется ядро версии **6.16+** (введена полная поддержка FEAT_NV2) и QEMU **10.1+**.
1. **Параметры загрузки:**
   Отредактируйте `/etc/default/grub` (или конфиг вашего загрузчика):
   ```text
   GRUB_CMDLINE_LINUX_DEFAULT="... kvm-arm.mode=nested"
   ```
2. **Проверка в dmesg:**
   ```bash
   dmesg | grep -i "kvm.*nested"
   # → kvm [1]: VHE+NV2 mode initialized successfully
   ```

### Сценарий 2: Настройка ВМ первого уровня (L1) в различных гипервизорах

#### Libvirt / virsh
Отредактируйте XML конфигурацию (`virsh edit <vm_name>`):
```xml
<cpu mode='host-passthrough' check='none'>
  <feature policy='require' name='vmx'/> <!-- Для Intel -->
  <feature policy='require' name='svm'/> <!-- Для AMD -->
</cpu>
```

#### Proxmox VE
Установите тип процессора `host`:
```bash
qm set <vmid> --cpu host
```

#### Vagrant
В `Vagrantfile` для провайдера `libvirt`:
```ruby
config.vm.provider :libvirt do |lv|
  lv.nested = true
  lv.cpu_mode = 'host-passthrough'
end
```

#### VMware Workstation / Player
В настройках ВМ: `Settings` → `Processors` → установите галочку **"Virtualize Intel VT-x/EPT or AMD-V/RVI"**.

#### VirtualBox
Через CLI (графический интерфейс часто блокирует эту опцию):
```bash
VBoxManage modifyvm "<vm_name>" --nested-hw-virt on
```

### Сценарий 3: Настройка в облачных средах (2026)

| Провайдер | Требования и особенности | Настройка |
| :--- | :--- | :--- |
| **AWS** | Инстансы 8-го поколения (C8i, M8i) или Bare Metal. | Поддержка Nitro транслирует инструкции автоматически. |
| **Azure** | Серии v3-v6. Процессоры Cobalt 200 (ARM). | Включено по умолчанию на поддерживаемых типах. |
| **GCP** | Intel (Haswell+), AMD (N2D). | Флаг `--enable-nested-virtualization` при создании образа. |

**Важно:** Для L2-гостей в облаке может потребоваться настройка **IP Aliasing** или **MAC Spoofing**, чтобы обеспечить сетевую связность.

### Сценарий 4: Оптимизация для Windows (Hyper-V) в L1
Для работы Hyper-V внутри KVM необходимо включить «улучшения» (enlightenments) в XML libvirt:
```xml
<features>
  <hyperv>
    <relaxed state='on'/>
    <vapic state='on'/>
    <spinlocks state='on' retries='8191'/>
    <evmcs state='on'/> <!-- Critical for Intel performance -->
  </hyperv>
</features>
```

### Сценарий 5: Проверка внутри гостевой системы (L1)
Внутри ВМ L1 должны быть видны флаги аппаратного ускорения:
```bash
grep -Eoc '(vmx|svm)' /proc/cpuinfo
# → Результат > 0 означает успех. На ARM64 проверяйте 'virt' или 'el2'.
```

## Диагностика и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `modprobe -r` выдает ошибку | Модуль занят активными ВМ | Остановите все ВМ на хосте перед перезагрузкой модуля. |
| Флаги в L1 не появились | CPU mode не `host` | Проверьте, что в конфиге не указана модель (например, `qemu64`). |
| Ошибка `VMX disabled by BIOS` | Заблокировано в прошивке | Включите VT-x/AMD-V в BIOS/UEFI физического сервера L0. |
| Сеть в L2 недоступна | Блокировка MAC-адресов | Включите `promisc` mode или разрешите MAC Spoofing на уровне L1. |
| Крайне низкая производительность L2 | Отсутствие аппаратного ускорения | Убедитесь, что в L1 загружен модуль `kvm_intel` или `kvm_amd`. |

## Дополнительная информация

- [Вложенная виртуализация: Определения и концепции](./definitions_and_concepts.md)
- [Вложенная виртуализация: Дополнительная информация](./additional_info.md) — детали производительности и MTU.
- [KVM — Управление через virsh](../kvm/management.md)
- [Оптимизация KVM (2026)](../kvm/performance_tuning_2026.md)
