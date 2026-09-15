<?php
function createModeRadioButtonIcon($name, $icon, $checked_icon, $checked, $n_buttons) {
  if ($checked) {
    $checked_string = 'checked';
    $icon = $checked_icon;
  } else {
    $checked_string = 'unchecked';
  }
  $max_width = 100 / $n_buttons;
  $style_size = "min(12vh, calc({$max_width}vw - 2rem - 2px))";
  echo "<div class=\"$checked_string\">\n";
  echo "  <svg class=\"bi\" style=\"height: $style_size; width: $style_size;\" fill=\"currentColor\">\n";
  echo "    <use href=\"media/bootstrap-icons.svg#$icon\" />\n";
  echo "  </svg>\n";
  echo "  <p class=\"mb-0 mt-2\">$name</p>\n";
  echo "</div>\n";
}

function createModeRadioButtonIcons($name, $icon, $checked_icon, $n_buttons) {
  createModeRadioButtonIcon($name, $icon, $checked_icon, false, $n_buttons);
  createModeRadioButtonIcon($name, $icon, $checked_icon, true, $n_buttons);
}

function createModeRadioButton($current_mode, $mode_name, $text, $icon, $n_buttons, $checked_icon = null) {
  if (is_null($checked_icon)) {
    $checked_icon = $icon . '-fill';
  }
  echo "<label class=\"btn btn-bm px-3" . (($current_mode == MODE_VALUES[$mode_name]) ? ' active' : '') . " disabled\">\n";
  echo "<input type=\"radio\" class=\"btn-check\" name=\"mode_radio\" id=\"mode_radio_$mode_name\" autocomplete=\"off\" disabled" . (($current_mode == MODE_VALUES[$mode_name]) ? ' checked' : '') . " value=\"" . MODE_VALUES[$mode_name] . "\">\n";
  createModeRadioButtonIcons($text, $icon, $checked_icon, $n_buttons);
  echo "</label>\n";
}
