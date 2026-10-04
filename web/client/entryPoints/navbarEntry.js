// @flow
/**
 * Use this entry point for HTML templates where Navbar is the ONLY JS
 * dependency.
 *
 * If a template has other JS dependencies, create a new entry point for it and
 * render the Navbar within that entry point. Do not include navbarEntry.js as
 * well, otherwise you'll be downloading a lot of duplicate boilerplate.
 */
import 'translate';
import Navbar from 'components/Navbar';

Navbar.renderToDOM();
