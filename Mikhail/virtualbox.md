# Установка VirtualBox и Extension Pack в Arch Linux

Это руководство описывает, как установить последнюю версию VirtualBox, VirtualBox Guest Additions и Extension Pack в Arch Linux. Arch Linux — один из самых настраиваемых дистрибутивов Linux. В Arch Linux вы можете легко получить последнюю версию VirtualBox из зеркал Pacman или напрямую из AUR.

### Что такое VirtualBox?

VirtualBox — это бесплатный кроссплатформенный продукт для виртуализации. Это один из наиболее часто используемых гипервизоров для домашнего/личного использования. Он позволяет запускать более одной операционной системы поверх существующей. VirtualBox бесплатен для использования и может работать в системах Windows, Linux и Unix.

Одним из главных преимуществ VirtualBox перед бесплатным VMware Player является то, что инструмент Vagrant для управления виртуальными машинами бесплатен для использования с VirtualBox. Однако с VMware вам придется использовать платную версию Vagrant.

Сначала обновите списки пакетов:

```bash
sudo pacman -Syy
```

Обновите GPG ключи:

```bash
sudo pacman -Sy archlinux-keyring
sudo pacman-key --populate archlinux
```

Выполните обновление системы, установите заголовки ядра и перезагрузите систему:

```bash
sudo pacman -Syu
sudo pacman -S linux-headers
sudo reboot
```

## Установка VirtualBox в Arch Linux

Установить VirtualBox в Arch Linux просто. Выполните следующую команду в терминале:

```bash
sudo pacman -S virtualbox virtualbox-guest-iso
```

Во время установки вам будет предложено выбрать провайдера для `VIRTUALBOX-HOST-MODULES`. Обычно подходит вариант по умолчанию (`virtualbox-host-dkms`).

После установки добавьте вашего текущего пользователя в группу `vboxusers`. Это предоставит пользователю права на управление виртуальными машинами.

```bash
sudo gpasswd -a $USER vboxusers
```

Следующим шагом является включение автоматической загрузки модулей ядра VirtualBox при запуске системы.

```bash
sudo systemctl enable vboxweb.service
```

## Установка VirtualBox Extension Pack в Arch Linux

На этом этапе мы установили VirtualBox и `virtualbox-guest-iso`. Осталось установить Extension Pack, который обеспечивает поддержку устройств USB 2.0, VirtualBox RDP и загрузку по PXE для карт Intel.

Для установки Extension Pack рекомендуется использовать `yay` (или другой AUR хелпер).

1.  **Установка yay (если не установлен):**

    ```bash
    sudo pacman -S --needed git base-devel
    git clone https://aur.archlinux.org/yay-bin.git
    cd yay-bin
    makepkg -si
    ```

2.  **Установка VirtualBox Extension Pack:**

    Выполняйте команду от обычного пользователя, не от root.

    ```bash
    yay -S virtualbox-ext-oracle --noconfirm
    ```

В случае, если вы скачали Extension Pack вручную с веб-сайта Oracle VirtualBox, вы можете использовать следующую команду для установки:

```bash
VBoxManage extpack install <имя_файла>.vbox-extpack
```

Если вы планируете использовать [phpVirtualBox](https://wiki.archlinux.org/index.php/PhpVirtualBox), вы можете включить его запуск при загрузке системы.

```bash
sudo systemctl enable vboxweb.service
sudo systemctl start vboxweb.service
```

Запустите модули VirtualBox вручную:

```bash
sudo /sbin/rcvboxdrv setup
```

Затем проверьте:

```bash
ps ax | grep -i vbox
```

---
Источник: [Install VirtualBox and Extension Pack in Arch Linux | ComputingForGeeks](https://computingforgeeks.com/install-latest-virtualbox-and-extension-pack-in-arch-linux/)