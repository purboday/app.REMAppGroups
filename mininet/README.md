Running the app with Mininet
----------------------------

The apps can run on the development VM (that has RIAPS installed) under mininet. The latest version of RIAPS must be installed. To install mininet, follow the instructions at http://mininet.org/download/ (Option 2) and then run ```pip3 install mininet```.

Note: rpyc_registry, and riaps services (e.g. riaps_deplo) must NOT be running on the VM.
These can be halted as follows:
```
	systemctl disable riaps-deplo.service
	systemctl stop riaps-deplo.service || true
	systemctl disable riaps-rpyc-registry.service
	systemctl stop riaps-rpyc-registry.service || true
```
Also, the nic_name in /etc/riaps/riaps.conf needs to be commented.

To start a mininet-based run (in this directory).
```
   source setup-mn
   riaps-mn N
```
where N is the number of virtual mininet hosts to be launched.

 At the mininet prompt:
 ```
    mininet> source SCRIPT
 ```
 where SCRIPT is the name of the .mn script. (e.g. remapp.mn). To change the number of virtual hosts, the .mn file needs to be updated with additional entries for each host.
 
> Note: mininet does not handle exceptions well, so if the last command fails it may leave the 
 (virtual) network interfaces behind - and a restart of the VM may be necessary.
 
> Note: the startup on the virtual nodes can take a few seconds.
 
 
 Running the app with Mininet in a RIAPS development environment
 ----------------------------------------------------------------
 
The app can be run on a VM that is being used to develop the RIAPS platform itself as follows.
Assume $RIAPS points to the root folder of the RIAPS source tree, and $APP points to this folder.
```
	cd $RIAPS 
	source setup
	cd $APP
	souce setup-mn.dev
	riaps-mn N
```
where N is the number of virtual mininet hosts to be launched.