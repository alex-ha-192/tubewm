#include "deco-theme.hpp"
#include <wayfire/core.hpp>
#include <wayfire/opengl.hpp>
#include <algorithm>
#include <cmath>
#include <cassert>
#include <pango/pangocairo.h>

namespace wf
{
namespace decor
{
/** Create a new theme with the default parameters */
decoration_theme_t::decoration_theme_t()
{}

/** @return The available height for displaying the title */
int decoration_theme_t::get_title_height() const
{
    return title_height;
}

/** @return The available border for resizing */
int decoration_theme_t::get_border_size() const
{
    return border_size;
}

/** @return The available border for resizing */
void decoration_theme_t::set_buttons(button_type_t flags)
{
    button_flags = flags;
}

/**
 * Fill the given rectangle with the background color(s).
 *
 * @param fb The target framebuffer, must have been bound already
 * @param rectangle The rectangle to redraw.
 * @param scissor The GL scissor rectangle to use.
 * @param active Whether to use active or inactive colors
 */
void decoration_theme_t::render_background(const wf::scene::render_instruction_t& data,
    wf::geometry_t rectangle, bool active) const
{
    wf::color_t color = active ? active_color : inactive_color;
    data.pass->add_rect(color, data.target, rectangle, data.damage);
}

/**
 * Render the given text on a cairo_surface_t with the given size.
 * The caller is responsible for freeing the memory afterwards.
 *
 * tubewm: the title sits on the left at a quiet size (15px in a 32px bar),
 * centred vertically and cut with an ellipsis when it does not fit.
 */
cairo_surface_t*decoration_theme_t::render_text(std::string text,
    int width, int height) const
{
    const auto format = CAIRO_FORMAT_ARGB32;
    auto surface = cairo_image_surface_create(format, width, height);

    if (height == 0)
    {
        return surface;
    }

    wf::color_t color = font_color;
    auto cr = cairo_create(surface);

    const double font_size = height * 15.0 / 32.0;
    const int pad = (int)(height * 12.0 / 32.0);

    PangoFontDescription *font_desc;
    PangoLayout *layout;

    font_desc = pango_font_description_from_string(((std::string)font).c_str());
    pango_font_description_set_absolute_size(font_desc, font_size * PANGO_SCALE);

    layout = pango_cairo_create_layout(cr);
    pango_layout_set_font_description(layout, font_desc);
    pango_layout_set_text(layout, text.c_str(), text.size());
    pango_layout_set_single_paragraph_mode(layout, true);
    pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
    pango_layout_set_width(layout, std::max(0, width - 2 * pad) * PANGO_SCALE);

    int text_w, text_h;
    pango_layout_get_pixel_size(layout, &text_w, &text_h);
    cairo_move_to(cr, pad, (height - text_h) / 2.0);
    cairo_set_source_rgba(cr, color.r, color.g, color.b, color.a);
    pango_cairo_show_layout(cr, layout);
    pango_font_description_free(font_desc);
    g_object_unref(layout);
    cairo_destroy(cr);

    return surface;
}

/**
 * tubewm: Metro buttons. Flat and square, the full height of the bar. A thin
 * glyph in the title colour; on hover the close button fills red and its X
 * turns white, other buttons get a faint wash. Pressing lightens the fill.
 */
cairo_surface_t*decoration_theme_t::get_button_surface(button_type_t button,
    const button_state_t& state) const
{
    cairo_surface_t *button_surface = cairo_image_surface_create(
        CAIRO_FORMAT_ARGB32, state.width, state.height);

    auto cr = cairo_create(button_surface);

    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);

    const double hover   = std::min(1.0, std::abs(state.hover_progress));
    const bool pressed   = state.hover_progress < -1e-3;
    const bool close     = (button == BUTTON_CLOSE);
    wf::color_t glyph    = font_color;

    if (hover > 1e-3)
    {
        if (close)
        {
            /* #e81123, or #f1707a while pressed */
            if (pressed)
            {
                cairo_set_source_rgba(cr, 0xf1 / 255.0, 0x70 / 255.0, 0x7a / 255.0, hover);
            } else
            {
                cairo_set_source_rgba(cr, 0xe8 / 255.0, 0x11 / 255.0, 0x23 / 255.0, hover);
            }

            glyph.r = glyph.r + (1.0 - glyph.r) * hover;
            glyph.g = glyph.g + (1.0 - glyph.g) * hover;
            glyph.b = glyph.b + (1.0 - glyph.b) * hover;
            glyph.a = glyph.a + (1.0 - glyph.a) * hover;
        } else
        {
            cairo_set_source_rgba(cr, glyph.r, glyph.g, glyph.b, (pressed ? 0.3 : 0.15) * hover);
        }

        cairo_rectangle(cr, 0, 0, state.width, state.height);
        cairo_fill(cr);
    }

    /* The glyph: 10px in a 32px bar, a 1px line */
    const double size = state.height * 10.0 / 32.0;
    const double cx   = state.width / 2.0;
    const double cy   = state.height / 2.0;
    const double h    = size / 2.0;

    cairo_set_source_rgba(cr, glyph.r, glyph.g, glyph.b, glyph.a);
    cairo_set_line_width(cr, state.border);
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_SQUARE);
    switch (button)
    {
      case BUTTON_CLOSE:
        cairo_move_to(cr, cx - h, cy - h);
        cairo_line_to(cr, cx + h, cy + h);
        cairo_move_to(cr, cx + h, cy - h);
        cairo_line_to(cr, cx - h, cy + h);
        break;

      case BUTTON_TOGGLE_MAXIMIZE:
        cairo_rectangle(cr, cx - h, cy - h, size, size);
        break;

      case BUTTON_MINIMIZE:
        cairo_move_to(cr, cx - h, cy);
        cairo_line_to(cr, cx + h, cy);
        break;

      default:
        assert(false);
    }

    cairo_stroke(cr);
    cairo_destroy(cr);

    return button_surface;
}
}
}
