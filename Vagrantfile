# -*- mode: ruby -*-
# vi: set ft=ruby :

# Stripped-down Vagrantfile for development



# Vagrantfile API/syntax version. Don't touch unless you know what you're doing!
VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|

  config.vm.box = "yungsang/boot2docker"

  config.vm.provider :virtualbox do |vbox, override|
    vbox.memory = 1024
    vbox.cpus = 2
  end

  config.vm.provider :vmware_fusion do |vmware, override|
    vmware.vmx["memsize"] = "1024"
    vmware.vmx["numvcpus"] = "2"
  end

  config.ssh.forward_agent = true

  # config.vm.customize [
  #   'modifyvm', :id,
  #   "--natdnshostresolver1", "on",
  #   "--natdnsproxy1", "on",
  # ]
  config.vm.network "private_network", ip: "192.168.10.200"

  # Fix busybox/udhcpc issue
  config.vm.provision :shell do |s|
    s.inline = <<-EOT
      if ! grep -qs ^nameserver /etc/resolv.conf; then
        sudo /sbin/udhcpc
      fi
      cat /etc/resolv.conf
    EOT
  end

  # Adjust datetime after suspend and resume
  config.vm.provision :shell do |s|
    s.inline = <<-EOT
      sudo /usr/local/bin/ntpclient -s -h pool.ntp.org
      date
    EOT
  end

  # Share ports 5000 - 5009
  10.times do |n|
    config.vm.network "forwarded_port", guest: 5000+n, host: 5000+n, host_ip: "127.0.0.1"
  end

  config.vm.network "forwarded_port", guest: 8000, host: 8000, host_ip: "127.0.0.1"
  config.vm.network "forwarded_port", guest: 5555, host: 5555, host_ip: "127.0.0.1"

  # This will share any folder in the parent directory that
  # has the name share-*
  # It mounts it at the root without the 'share-' prefix
  config.vm.synced_folder ".","/inbox"

  share_prefix = "share-"
  Dir['../*/'].each do |fname|
    basename = File.basename(fname)
    if basename.start_with?(share_prefix)
      mount_path = "/" + basename[share_prefix.length..-1]
      puts "Mounting share for #{fname} at #{mount_path}"
      config.vm.synced_folder fname, mount_path
    end
  end

  # See: https://stackoverflow.com/questions/14715678/vagrant-insecure-by-default
  unless Vagrant.has_plugin?("vagrant-rekey-ssh")
    warn "------------------- SECURITY WARNING -------------------"
    warn "Vagrant is insecure by default.  To secure your VM, run:"
    warn "    vagrant plugin install vagrant-rekey-ssh"
    warn "--------------------------------------------------------"
  end
end

# Local Vagrantfile overrides.  See Vagrantfile.local.example for examples.
Dir.glob('Vagrantfile.local.d/*').sort.each do |path|
  load path
end
Dir.glob('Vagrantfile.local').sort.each do |path|
  load path
end
