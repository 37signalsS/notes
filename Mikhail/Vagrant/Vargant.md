Установка:

``` sh
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
```

``` sh
sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com (lsb_release -cs) main"
```

``` sh
sudo apt-get update && sudo apt-get install vagrant 
```

Создаем директорию а в ней директории для каждой виртуалки

И выполним в ней процесс инициализации, в ходе которого Vagrant создаст конфигурационный файл Vagrantfile:

``` sh
vagrant init generic/ubuntu2010 
```

Создался Vagrantfile с примерно таким содержимым:

```
Vagrant.configure("2") do |config|
  config.vm.box = "generic/ubuntu2010"
end 
```

- Запустить виртуальную машину с атрибутом, отвечающим за используемый провайдер:

``` sh
vagrant up --provider=virtualbox 
```

- Список запущенных машин:

``` sh
vagrant status 
```

- Узнать все о ssh подключении:

``` sh
vagrant ssh-config
```

- Подключиться к виртуалке:

``` sh
vagrant ssh
```

- Удалить виртуалку:

``` sh
vagrant destroy
```

- Назначить имя хоста:

``` sh
config.vm.hostname = ""
```

- Сеть

```
config.vm.network :private_network, ip: ""
```

- При измении конфига вируалки, если в статусе ничего не изменилось:

``` sh
rm -rf .vagrant
```

- Выключить обновление виртуалки при старте

```
config.vm.box_sheck_update = false
```

Конфиг на несколько виртуалок:

``` sh
$script = <<-SCRIPT 
# Тут пишем что необходтмо установить и т.д.

nodes = [
    { hostname: 'ubuntu1', ip: '10.245.1.222', memory: 1024, cpu: 1, boxname: "ubuntu/xenial64" },
    { hostname: 'ubuntu2', ip: '10.245.1.223', memory: 1024, cpu: 1, boxname: "ubuntu/xenial64" }
]

Vagrant.configure("2") do |config|
    nodes.each do |node|
        config.vm.box_check_update = false
        config.vm.define node[:hostname] do |nodeconfig|
            nodeconfig.vm.box = node[:boxname]
            nodeconfig.vm.hostname = node[:hostname]
            nodeconfig.vm.network :private_network, ip: node[:ip]
            nodeconfig.vm.provider :virtualbox do |vb|
                vb.memory = node[:memory]
                vb.cpus = node[:cpu]
            end
            # Здесь предполагается, что $script определён заранее или можно указать команду shell напрямую
            nodeconfig.vm.provision "shell", inline: $script
        end
    end
end

```

- Использовать прокси:

``` sh
export https_proxy="http://norwH:naponb@ip_npokcu:nopt/*
export VAGRANT_HTTP_PROXY=${http_proxy}
export VAGRANT_NO_PROXY="127.0.0.1"
```

- Использовать Tailscale:

```
Vagrant.configure("2") do |config|
  config.env.enable

  config.vm.box = ENV['VM_BOX']
  config.vm.hostname = ENV['VM_HOSTNAME']    
  config.vm.provider ENV['VM_ENGINE'] do |v| 
    v.name = ENV['VM_HOSTNAME']
    v.memory = ENV['VM_MEMORY']
    v.cpus = ENV['VM_CPUS']
  end

  config.vm.provision "tailscale-install", type: "shell" do |s|
    s.inline = "curl -fsSL https://tailscale.com/install.sh | sh"
  end

  config.vm.provision "tailscale-up", type: "shell" do |s|
    s.inline = "tailscale up --ssh --operator=vagrant --authkey #{ENV['TAILSCALE_AUTHKEY']}"
  end

  config.trigger.before :destroy do |trigger|
    trigger.run_remote = {inline: "tailscale logout"}
    trigger.on_error = :continue
  end

end
```

- Данных о провайдере, размере оперативной памяти и количестве ядер:

```
config.vm.provider "virtualbox" do |v|
    v.memory=2048
    v.cpus=2
end
```
 

В Vagrant можно настраивать provision, то есть настройку программ виртуальной машины, фактически перечисляя список команд. 

Пишем скрипт развёртывания Nginx:

``` sh
#!/bin/sh

echo 'deb https://nginx.org/packages/ubuntu/ focal nginx' > /etc/apt/sources.list.d/nginx.list
echo 'deb-src https://nginx.org/packages/ubuntu/ focal nginx' >> /etc/apt/sources.list.d/nginx.list
apt-key adv --keyserver keyserver.ubuntu.com --recv-keys ABF5BD827BD9BF62
apt-get update -y
apt-get install nginx -y
systemctl enable nginx
systemctl start nginx 
```

Поправим Vagrantfile, чтобы он прочитал и выполнил bash-скрипт при развёртывании виртуальной машины:

```
config.vm.provision :shell,
path: "bootstrap.sh" 
```

Запускаем виртуалку:

``` sh
vagrant up 
```

(или vagrant reload --provision  если виртуалка уже запускалась ранее) и проверяем изнутри:

``` sh
wget -qO- 127.0.0.1
```

Чтобы сделать сайт доступным снаружи, нужно пробросить порты с гостевой ОС на основную (port forwarding):

```
config.vm.network :forwarded_port,
guest: 80,
host: 8080 

```

Обновляем:

``` sh
vagrant reload --provision 
```





