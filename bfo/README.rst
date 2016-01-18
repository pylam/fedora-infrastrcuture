iPXE Booting Fedora aka BFO
===========================
boot.fedoraproject.org (BFO) is a way to boot hosts in order to run installers
or other types of media via the network. It works similarly to a pxeboot environment.

Core Components
---------------
- iPXE (http://ipxe.org)
- Fedora pxe images (vmlinuz, initrd)
- Embedded iPXE boot script in the BFO images
- Network loaded boot menus and options
- Public install trees for Fedora

Updating iPXE Images
--------------------
To update the boot images follow this manual process.

Ensure the following dependencies are installed:

::
  dnf groupinstall 'Development Tools'
  dnf install syslinux-nonlinux xz-devel 

Clone the repos and build:

::
  git clone ssh://fasusername@git.fedorahosted.org/git/fedora-infrastructure.git
  cd fedora-infrastructure/bfo
  git clone git://git.ipxe.org/ipxe.git
  cd ipxe/src
  make EMBED=../../script0.ipxe

Update the alt images from the following build artifacts:

::
  bin/ipxe.iso
  bin/ipxe.dsk
  bin/ipxe.lkrn
  bin/ipxe.usb

Making Menu Changes
--------------------
Periodiclly we need to update the menu items. To update menu items follow this manual process.

Clone the repo:

::
  git clone ssh://fasusername@git.fedorahosted.org/git/fedora-infrastructure.git
  cd fedora-infrastructure/bfo/pxelinux.cfg

Make the needed changes to the menu configurations in this directory.
The menus are loaded in the following order (check default for the latest):

::
  default
  - fedora_install.conf
  - fedora_rescue.conf
  - fedora_rawhide.conf
  - fedora_prerelease.conf
  - fedora_eol.conf
  - utilities.conf
  - bfo.conf

Commit and push your changes:

::
  git commit -a
  git push origin

XXX: Need info on how to publish the menu changes to alt.

Testing Changes
---------------
To be able to test changes before publishing them, you can use Fedora People hosting and KVM.

Clone the repos, configure for your Fedora People and build:

::
  git clone ssh://fasusername@git.fedorahosted.org/git/fedora-infrastructure.git
  cd fedora-infrastructure/bfo
  git clone git://git.ipxe.org/ipxe.git
  cd ipxe/src
  cat << EOF > script0.ipxe
  #!ipxe
  set 209:string pxelinux.cfg/default
  set 210:string https://fasusername.fedorapeople.org/bfo/
  dhcp || goto manualnet
  chain https://fasusername.fedorapeople.org/bfo/pxelinux.0
  :manualnet
  echo Please provide, IP address, Netmask, Gateway and Router
  ifopen net0
  config net0
  chain https://fasusername.fedorapeople.org/bfo/pxelinux.0
  EOF
  make EMBED=script0.ipxe

From the root of the fedora-infrastructure repo, copy your menu items to Fedora People:

::
  scp -r bfo fasusername@fedorapeople.org/public_html/

If needed, also put the latest copy of pxelinux.0 there:

::
  scp /usr/share/syslinux/pxelinux.0 fasusername@fedorapeople.org/public_html/bfo/

Boot the ipxe.iso:

::
  qemu-kvm -m 1024 bin/ipxe.iso

Interact with the menu items as needed for testing your changes.


