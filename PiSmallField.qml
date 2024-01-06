import QtQuick 2.1
import QtQuick.Layouts 1.10
import QtGraphicalEffects 1.0
import QtQuick.Window 2.5

Text {
    property string field_name: ''
    property string text_prefix: ''
    property string text_suffix: ''
    property bool is_recently_changed: field_name != '' && camera.last_changed == field_name
    font.pixelSize: 30
    style: Text.Outline
    styleColor: "#333"
    color: is_recently_changed ? "yellow" : "white"
    text: text_prefix + camera[field_name] + text_suffix
}
