# Вложенная виртуализация: Практические сценарии

## Включение в KVM (Linux)

### 1. Проверка текущего состояния

```bash
# Проверка загруженных модулей
lsmod | grep -i kvm

# Статус nested (Intel)
cat /sys/module/kvm_intel/parameters/nested

# Статус nested (AMD)
cat /sys/module/kvm_amd/parameters/nested
```

**Значения:** `1` или `Y` = включено, `0` или `N` = выключено.

> **Примечание:** На Ubuntu nested virtualization включён по умолчанию.

### 2. Временное включение (до перезагрузки)

```bash
# Intel
sudo modprobe -r kvm_intel
sudo modprobe kvm_intel nested=1

# AMD
sudo modprobe -r kvm_amd
sudo modprobe kvm_amd nested=1
```

### 3. Постоянное включение

**Файл `/etc/modprobe.d/kvm.conf`:**

```
# Intel
options kvm-intel nested=1

# AMD
options kvm-amd nested=1
```

**Применение:**

```bash
# Перезагрузка модуля
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel

# Или перезагрузка системы
sudo reboot
```

### 4. Проверка внутри L1 ВМ

```bash
# Проверка флагов виртуализации
egrep "svm|vmx" /proc/cpuinfo
```

**Пустой вывод?** Требуется настройка ВМ:

**libvirt/virsh:**

```bash
virsh edit <vm-name>
```

**Добавить в XML:**

```xml
<cpu mode='host-model' check='partial'>
  <feature policy='require' name='vmx'/>  <!-- для Intel -->
  <feature policy='require' name='svm'/>  <!-- для AMD -->
</cpu>
```

**QEMU командная строка:**

```bash
qemu-system-x86_64 -cpu host ...
```

---

## Сценарии использования

### 1. Разработка и тестирование

**Сценарий:** Тестирование гипервизоров, облачных платформ (OpenStack, Kubernetes + KubeVirt).

**Преимущества:**

- Один физический хост → множество вложенных ВМ
- Не требуется парк серверов
- Быстрое развертывание/удаление

### 2. Облачные провайдеры

**Примеры:** AWS, Google Cloud, Azure.

**Использование:**

- Предоставление клиентам возможности запускать свои гипервизоры
- Изоляция арендаторов через вложенную виртуализацию

### 3. Безопасность (Sandbox)

**Сценарий:** Запуск недоверенного ПО в дополнительном слое изоляции.

**Схема:**

```
Хост (L0) → ВМ-песочница (L1) → Подозрительное ПО (L2)
```

**Преимущества:**

- Дополнительный барьер при побеге из L2
- Изоляция сетевого трафика

### 4. Обучение и лабораторные стенды

**Сценарий:** Создание сложных сетевых топологий на одном ПК.

**Примеры:**

- Кластер Kubernetes из нескольких ВМ
- Сеть с маршрутизаторами внутри ВМ
- Тестирование миграции ВМ

---

*См. также: [определения и концепции](./definitions_and_concepts.md), [дополнительная информация](./additional_info.md)*
