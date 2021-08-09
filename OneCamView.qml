import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.11
import QtQuick.Window 2.2
import QtQuick.Controls.Material 2.12

ApplicationWindow {
    width: 480
    height: 270
    visible: true

    StackLayout {
        anchors.fill: parent
        currentIndex: camera.status == 'online' ? 1 : 0
        Rectangle {
            Text {
                anchors.fill: parent
                text: camera.status
            }
        }

        ColumnLayout {
            spacing: 0

            focus: true
            Keys.onPressed: {
                if (event.key == Qt.Key_Left) {
                    event.accepted = camera.handle_key('left');
                } else if (event.key == Qt.Key_Right) {
                    event.accepted = camera.handle_key('right');
                }

            }

            RowLayout {
                spacing: 0
                Layout.preferredHeight: 100

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: '#333333'
                    Text {
                        text: camera.autoexposuremode == camera.autoexposuremodedial ?
                            camera.autoexposuremode :
                            camera.autoexposuremodedial + ' ' + camera.autoexposuremode
                        anchors.fill: parent
                    }
                }

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: camera.last_changed == 'shutterspeed' ? '#ff6666' : camera.selected_mode == 'shutterspeed' ? '#6666ff' : '#333333'
                    border.width: camera.selected_mode == 'shutterspeed' ? 2 : 1
                    MouseArea {
                        anchors.fill: parent
                        onClicked: camera.selected_mode = 'shutterspeed'
                    }
                    Text {
                        text: camera.shutterspeed
                        anchors.fill: parent
                    }
                }

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: camera.last_changed == 'aperture' ? '#ff6666' : camera.selected_mode == 'aperture' ? '#6666ff' : '#333333'
                    border.width: camera.last_changed == 'aperture' || camera.selected_mode == 'aperture' ? 2 : 1
                    MouseArea {
                        anchors.fill: parent
                        onClicked: camera.selected_mode = 'aperture'
                    }
                    Text {
                        text: camera.aperture
                        anchors.fill: parent
                    }
                }
            }

            RowLayout {
                spacing: 0
                Layout.preferredHeight: 100

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: camera.last_changed == 'iso' ? '#ff6666' : camera.selected_mode == 'iso' ? '#6666ff' : '#333333'
                    border.width: camera.last_changed == 'iso' || camera.selected_mode == 'iso' ? 2 : 1
                    MouseArea {
                        anchors.fill: parent
                        onClicked: camera.selected_mode = 'iso'
                    }
                    Text {
                        text: 'ISO ' + camera.iso
                        anchors.fill: parent
                    }
                }

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: camera.last_changed == 'exposurecompensation' ? '#ff6666' : camera.selected_mode == 'exposurecompensation' ? '#6666ff' : '#333333'
                    border.width: camera.selected_mode == 'exposurecompensation' ? 2 : 1
                    MouseArea {
                        anchors.fill: parent
                        onClicked: camera.selected_mode = 'exposurecompensation'
                    }
                    Text {
                        text: camera.exposurecompensation + ' EV'
                        anchors.fill: parent
                    }
                }
            }

            RowLayout {
                spacing: 0
                Layout.preferredHeight: 80

                Rectangle {
                    implicitWidth: 200
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: camera.last_changed.startsWith('whitebalance') || camera.last_changed == 'colortemperature' ? '#ff6666' : camera.selected_mode == 'wb' ? '#6666ff' : '#333333'
                    border.width: camera.selected_mode == 'wb' ? 2 : 1
                    MouseArea {
                        anchors.fill: parent
                        onClicked: camera.selected_mode = 'wb'
                    }
                    Text {
                        text: {
                            let mainWB = camera.whitebalance == 'Color Temperature' ? camera.colortemperature + 'K' : camera.whitebalance;
                            let shiftAB = '';
                            if (camera.whitebalanceadjusta > 0) {
                                shiftAB = 'A' + camera.whitebalanceadjusta;
                            } else if (camera.whitebalanceadjusta < 0) {
                                shiftAB = 'B' + (-parseInt(camera.whitebalanceadjusta));
                            }
                            let shiftMG = '';
                            if (camera.whitebalanceadjustb > 0) {
                                shiftMG = 'G' + camera.whitebalanceadjustb;
                            } else if (camera.whitebalanceadjustb < 0) {
                                shiftMG = 'M' + (-parseInt(camera.whitebalanceadjustb));
                            }
                            return mainWB + (shiftAB != '' || shiftMG != '' ? ' ' : '') + shiftAB + shiftMG;
                        }
                        anchors.fill: parent
                    }
                }

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    border.color: camera.last_changed == 'movieservoaf' || camera.last_changed == 'manualfocusdrive' ? '#ff6666' : camera.selected_mode == 'movieservoaf' ? '#6666ff' : '#333333'
                    border.width: camera.selected_mode == 'movieservoaf' ? 2 : 1
                    MouseArea {
                        anchors.fill: parent
                        onClicked: camera.selected_mode = 'movieservoaf'
                    }
                    Text {
                        text: camera.movieservoaf
                        anchors.fill: parent
                    }
                }
            }

            RowLayout {
                spacing: 0
                Layout.preferredHeight: 50

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Text {
                        text: camera.cameramodel
                        anchors.fill: parent
                    }
                }

                Rectangle {
                    implicitWidth: 100
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Text {
                        text: camera.lensname
                        anchors.fill: parent
                    }
                }
            }
        }
    }
}
