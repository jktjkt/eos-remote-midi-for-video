import QtQuick 2.1
import QtQuick.Layouts 1.10
import QtGraphicalEffects 1.0
import QtQuick.Window 2.5

Window {
    width: 1920
    height: 1080
    color: "black"
    screen: Qt.application.screens[0]
    visible: true

    function wb_text(camera) {
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
        return (shiftAB == '' && shiftMG == '' && camera.whitebalance == 'Auto' ? 'WB ' : '') + mainWB + (shiftAB != '' || shiftMG != '' ? ' ' : '') + shiftAB + shiftMG;
    }

    function on_onecam_refresh() {
        camera_model.visible = true;
        delayedHide.restart()
    }

    Timer {
        id: delayedHide
        interval: 2500
        onTriggered: camera_model.visible = false
    }

    Component.onCompleted: {
        cam_switched.timeout.connect(on_onecam_refresh)
        switcher_state.prop_changed.connect(on_onecam_refresh)
    }

    StackLayout {
        antialiasing: false
        anchors.fill: parent
        currentIndex: switcher_state.aux_content == 'MVW' ? 0 : (camera.status == 'online' ? 2 : 1)
        Rectangle {
            color: "transparent"
            Rectangle {
                x: 970
                y: 820
                width: 460
                height: 250
                color: camera.tally == "program" ? "#600" : camera.tally == "preview" ? "#040" : "#222"
                visible: camera.status == 'online'

                PiSmallField {
                    x: 410
                    y: 200
                    field_name: 'switcher_input'
                }

                PiSmallField {
                    id: small_camera
                    x: 20
                    y: 190
                    font.pixelSize: 20
                    text: camera.cameramodel
                }
                PiSmallField {
                    x: small_camera.x
                    y: 220
                    font.pixelSize: 20
                    text: camera.lensname
                }

                PiSmallField {
                    id: small_af
                    x: 20
                    y: 20
                    field_name: 'movieservoaf'
                    is_recently_changed: camera.last_changed == 'movieservoaf' || camera.last_changed == 'manualfocusdrive'
                    text: camera.movieservoaf == 'On' ? 'AF' : 'MF'
                }

                PiSmallField {
                    id: small_evcomp
                    x: 150
                    y: small_af.y
                    field_name: 'exposurecompensation'
                    text_suffix: ' EV'
                }

                PiSmallField {
                    id: small_aperture
                    x: small_af.x
                    y: 80
                    field_name: 'aperture'
                    text_prefix: 'F/'
                }
         
                PiSmallField {
                    id: small_shutterspeed
                    x: small_evcomp.x
                    y: small_aperture.y
                    field_name: 'shutterspeed'
                    text_suffix: 's'
                }
         
                PiSmallField {
                    id: small_iso
                    x: 300
                    y: small_aperture.y
                    field_name: 'iso'
                    text_prefix: 'ISO '
                }

                PiSmallField {
                    x: small_shutterspeed.x
                    y: 140
                    is_recently_changed: camera.last_changed.startsWith('whitebalance') || camera.last_changed == 'colortemperature'
                    text: wb_text(camera)
                }
           }
        }
        Rectangle {
            color: "transparent"
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 30
                font.pixelSize: 80
                text: camera.status
                color: "yellow"
            }
        }
        Rectangle {
            color: "transparent"
            Rectangle {
                id: tally_indicator
                property bool is_tally_preview : camera.tally == 'preview'
                radius: 150
                width: radius
                height: radius
                y: 30
                // x: 1920 - y - radius
                x: y
                color: camera.tally == "program" ? "red" : camera.tally == "preview" ? "green" : "transparent"
                Text {
                    text: camera.switcher_input
                    anchors.centerIn: parent
                    color: camera.tally == "program" || camera.tally == "preview" ? "black" : "white"
                    font.pixelSize: parent.radius * 0.6
                    style: camera.tally != "program" && camera.tally != "preview" ? Text.Outline : Text.Normal
                    styleColor: "#333"
                }
                visible: camera.tally != '' || camera_model.visible
            }

            PiField {
                id: camera_model
                y: 50
                anchors.right: parent.right
                anchors.bottom: null
                anchors.bottomMargin: null
                anchors.rightMargin: 50
                text: camera.cameramodel
                color: "white"
            }

            PiField {
                y: 100
                anchors.right: parent.right
                anchors.bottom: null
                anchors.bottomMargin: null
                anchors.rightMargin: 50
                text: camera.lensname
                color: camera_model.color
                visible: camera_model.visible
            }

            PiField {
                y: 150
                anchors.right: parent.right
                anchors.bottom: null
                anchors.bottomMargin: null
                anchors.rightMargin: 50
                text: camera.autoexposuremode == camera.autoexposuremodedial ?
                    camera.autoexposuremode :
                    camera.autoexposuremodedial + ' ' + camera.autoexposuremode
                color: camera_model.color
                visible: camera_model.visible
            }

            PiField {
                x: 250
                field_name: 'movieservoaf'
                is_recently_changed: camera.last_changed == 'movieservoaf' || camera.last_changed == 'manualfocusdrive'
                text: camera.movieservoaf == 'On' ? 'AF' : 'MF'
            }

            PiField {
                x: 450
                field_name: 'exposurecompensation'
                text_suffix: ' EV'
            }
    
            PiField {
                x: 650
                field_name: 'aperture'
                text_prefix: 'F/'
            }
     
            PiField {
                x: 850
                field_name: 'shutterspeed'
                text_suffix: 's'
            }
     
            PiField {
                x: 1100
                field_name: 'iso'
                text_prefix: 'ISO '
            }
     
            PiField {
                x: 1450
                is_recently_changed: camera.last_changed.startsWith('whitebalance') || camera.last_changed == 'colortemperature'
                text: wb_text(camera)
            }
        }
    }
}
