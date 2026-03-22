#!/bin/sh
#
### BEGIN INIT INFO
# Provides:          comicarr
# Required-Start:    $all
# Required-Stop:     $all
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: starts Comicarr
# Description:       starts Comicarr
### END INIT INFO

# Source function library.
. /etc/init.d/functions

# Source Comicarr configuration
if [ -f /etc/sysconfig/comicarr ]; then
        . /etc/sysconfig/comicarr
fi

prog=comicarr
lockfile=/var/lock/subsys/$prog

## Edit user configuation in /etc/sysconfig/comicarr to change
## the defaults
username=${MY_USER-comicarr}
homedir=${MY_HOME-/opt/comicarr}
datadir=${MY_DATA-/opt/comicarr}
pidfile=${MY_PIDFILE-/var/run/comicarr/comicarr.pid}
nice=${MY_NICE-}
##

pidpath=`dirname ${pidfile}`
options=" --daemon --nolaunch --pidfile=${pidfile} --datadir=${datadir}"

# create PID directory if not exist and ensure the Comicarr user can write to it
if [ ! -d $pidpath ]; then
        mkdir -p $pidpath
        chown $username $pidpath
fi

if [ ! -d $datadir ]; then
        mkdir -p $datadir
        chown $username $datadir
fi

start() {
        # Start daemon.
        echo -n $"Starting $prog: "
        daemon --user=${username} --pidfile=${pidfile} ${nice} python ${homedir}/Comicarr.py ${options}
        RETVAL=$?
        echo
        [ $RETVAL -eq 0 ] && touch $lockfile
        return $RETVAL
}

stop() {
        echo -n $"Shutting down $prog: "
        killproc -p ${pidfile} python
        RETVAL=$?
        echo
        [ $RETVAL -eq 0 ] && rm -f $lockfile
        return $RETVAL
}

# See how we were called.
case "$1" in
  start)
        start
        ;;
  stop)
        stop
        ;;
  status)
        status $prog
        ;;
  restart|force-reload)
        stop
        start
        ;;
  try-restart|condrestart)
        if status $prog > /dev/null; then
            stop
            start
        fi
        ;;
  reload)
        exit 3
        ;;
  *)
        echo $"Usage: $0 {start|stop|status|restart|try-restart|force-reload}"
        exit 2
esac
