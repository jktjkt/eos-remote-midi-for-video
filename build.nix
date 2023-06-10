{ pkgs ? import <nixpkgs> { } }:

let
  libgphoto2 = pkgs.libgphoto2.overrideAttrs(attrs: {
    version = "2021-08-08";
    src = /home/jkt/work/prog/libgphoto2;
  });
  tmp_gphoto2 = pkgs.gphoto2.override {
    libgphoto2 = libgphoto2;
  };
  gphoto2 = tmp_gphoto2.overrideAttrs(attrs: {
    version = "2021-06-30";
    src = /home/jkt/work/prog/gphoto2;
  });
  my_python = pkgs.python310;
  # my_python_gphoto2 = my_python.pkgs.buildPythonPackage rec {
  # };
  my_python_gphoto2 = my_python.pkgs.gphoto2.override {
    libgphoto2 = libgphoto2;
  };
# in pkgs.mkShell.override {
#   stdenv = pkgs.gcc10Stdenv;
# } rec {
in pkgs.mkShell rec {
  name = "eos-remote-midi-for-videos";
  buildInputs = [
    my_python
    my_python.pkgs.mido
    my_python.pkgs.python-rtmidi
    my_python_gphoto2
    gphoto2
    pkgs.qt5.qtbase
    # pkgs.qt5.qtquick1
    # pkgs.qt5.qtquickcontrols
    # pkgs.qt5.qtquickcontrols2
    pkgs.qt5.qtwayland

    # my_python.pkgs.python-language-server
    # my_python.pkgs.rope
    my_python.pkgs.asyncio-mqtt
    my_python.pkgs.pyside2
  ];
}
